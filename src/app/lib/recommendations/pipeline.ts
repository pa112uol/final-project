import type { Seed, Track, PipelineClients } from "./types";
import { buildCandidates } from "./candidates";
import { buildTagWeights, MOOD_TAGS, normalizeTag } from "./tags";
import { filterSeeds, deduplicateByMbid, deduplicateByTitle } from "./dedup";
import { scoreAndSort } from "./scoring";
import { mmrSelect } from "./diversify";
import {
  RECOMMENDATION_LIMIT,
  TOP_TAGS_COUNT,
  MOOD_MULTIPLIER,
  MAX_TRACKS_PER_ARTIST,
} from "./constants";
import { BROAD_FETCH_TAGS } from "./tags";

export async function runPipeline(
  seeds: Seed[],
  apiKey: string,
  mood: string | undefined,
  novelty: number,
  clients: PipelineClients,
): Promise<Track[]> {
  const seedTagSets = await Promise.all(
    seeds.map(async (s) => {
      const [lbTags, lfTags] = await Promise.all([
        s.mbid ? clients.fetchRecordingTags(s.mbid) : Promise.resolve([]),
        clients.fetchTrackTags(s.title, s.artist, apiKey, s.mbid || undefined),
      ]);
      console.log(
        "lfTags for",
        s.title,
        ":",
        lfTags.map((t) => `${t.name}(${t.count})`).join(", ") || "(none)",
      );
      console.log(
        "lbTags for",
        s.title,
        ":",
        lbTags.map((t) => `${t.name}(${t.count})`).join(", ") || "(none)",
      );
      const { mergeTags } = await import("./tags");
      return mergeTags(lbTags, lfTags);
    }),
  );

  const mergedSummary = seedTagSets.map(
    (tags, i) =>
      `  seed[${i}] (${seeds[i].title} – ${seeds[i].artist}): ${tags.map((t) => `${t.name}(${t.count})`).join(", ") || "(none)"}`,
  );
  console.log("[tags/merged]\n" + mergedSummary.join("\n"));

  const tagWeights = buildTagWeights(seedTagSets);
  const sortedTags = [...tagWeights.entries()].sort((a, b) => b[1] - a[1]);

  if (sortedTags.length === 0) return [];

  // Exclude tags that match a seed artist name, e.g. "queen" for a Queen seed
  // would make fetchTagArtists return mostly Queen members and collaborators
  const seedArtistNames = new Set(seeds.map((s) => s.artist.toLowerCase()));

  // Prefer specific tags for fetching. Fallback to broad ones only when
  // fewer than 2 specific tags exist (e.g. a pure rock seed with no sub-genre)
  let fetchTags = sortedTags
    .filter(
      ([tag]) =>
        !BROAD_FETCH_TAGS.has(normalizeTag(tag)) && !seedArtistNames.has(tag),
    )
    .slice(0, TOP_TAGS_COUNT);
  if (fetchTags.length < 2) {
    fetchTags = sortedTags
      .filter(([tag]) => !seedArtistNames.has(tag))
      .slice(0, TOP_TAGS_COUNT);
  }

  console.log(
    "[tags] fetch tags:",
    fetchTags.map(([t, w]) => `${t}(${w.toFixed(0)})`).join(", "),
  );

  const rawCandidates = await buildCandidates(
    fetchTags,
    apiKey,
    novelty,
    clients,
  );

  // Sort for determinism before dedup (deduplicateByTitle keeps first winner)
  rawCandidates.sort((a, b) =>
    `${a.title}|||${a.artist}`.localeCompare(`${b.title}|||${b.artist}`),
  );

  // Compute track-level tag scores against the weighted seed profile
  const normalizedTagWeights = new Map<string, number>();
  for (const [tag, weight] of tagWeights) {
    normalizedTagWeights.set(normalizeTag(tag.toLowerCase()), weight);
  }
  for (const c of rawCandidates) {
    c.trackTagScore = c.tags.reduce(
      (sum, tag) =>
        sum + (normalizedTagWeights.get(normalizeTag(tag.toLowerCase())) ?? 0),
      0,
    );
  }

  let candidates = filterSeeds(rawCandidates, seeds);
  candidates = deduplicateByMbid(candidates);
  candidates = deduplicateByTitle(candidates);

  // Fetch LF track tags for same-artist pairs that still have no track-level
  // signal - only these need tie-breaking; skipping solos avoids the cost
  // when there's nothing to differentiate.
  const zeroScoreByArtist = new Map<string, typeof candidates>();
  for (const c of candidates) {
    if (c.trackTagScore === 0) {
      const key = c.artist.toLowerCase();
      if (!zeroScoreByArtist.has(key)) zeroScoreByArtist.set(key, []);
      zeroScoreByArtist.get(key)!.push(c);
    }
  }
  const tieBreakCandidates = [...zeroScoreByArtist.values()]
    .filter((cs) => cs.length >= 2)
    .flat();

  await Promise.allSettled(
    tieBreakCandidates.map(async (c) => {
      const lfTags = await clients.fetchTrackTagsOnly(
        c.title,
        c.artist,
        apiKey,
        c.mbid || undefined,
      );
      if (lfTags.length === 0) {
        console.log(`[tiebreak] "${c.title}" – ${c.artist}: no LF tags`);
        return;
      }
      c.tags = lfTags.map((t) => t.name);
      c.trackTagScore = c.tags.reduce(
        (sum, tag) =>
          sum +
          (normalizedTagWeights.get(normalizeTag(tag.toLowerCase())) ?? 0),
        0,
      );
      console.log(
        `[tiebreak] "${c.title}" – ${c.artist}: tags=[${c.tags.slice(0, 6).join(", ")}] trackTagScore=${c.trackTagScore.toFixed(1)}`,
      );
    }),
  );

  // For tracks with no listen count, fall back to artist-level popularity
  const artistMbids = candidates
    .filter((c) => c.listenCount === 0 && c.artistMbid)
    .map((c) => c.artistMbid);
  const lbArtistPopularity = await clients.fetchArtistPopularity([
    ...new Set(artistMbids),
  ]);
  for (const c of candidates) {
    if (c.listenCount === 0) {
      const count = lbArtistPopularity.get(c.artistMbid);
      if (count !== undefined) c.artistListenCount = count;
    }
  }

  if (mood && MOOD_TAGS[mood]) {
    const moodTagSet = new Set(MOOD_TAGS[mood]);
    for (const c of candidates) {
      if (c.tags.some((t) => moodTagSet.has(t.toLowerCase()))) {
        c.tagWeightSum *= MOOD_MULTIPLIER;
      }
    }
  }

  const artistTrackCount = new Map<string, number>();
  const top = mmrSelect(
    scoreAndSort(
      candidates.filter((c) => c.mbid),
      novelty,
    ).filter((c) => {
      const key = c.artist.toLowerCase();
      const count = artistTrackCount.get(key) ?? 0;
      if (count >= MAX_TRACKS_PER_ARTIST) return false;
      artistTrackCount.set(key, count + 1);
      return true;
    }),
    RECOMMENDATION_LIMIT,
  );

  console.log(
    "[candidates:final]\n" +
      top
        .map(
          (c, i) =>
            `  [${i + 1}] "${c.title}" – ${c.artist}` +
            `\n       mbid:${c.mbid || "none"}` +
            `\n       listens:${c.listenCount} users:${c.userCount} artistListens:${c.artistListenCount}` +
            `\n       relevance:${c.relevanceScore.toFixed(3)} novelty:${c.noveltyScore.toFixed(3)} final:${c.finalScore.toFixed(3)}` +
            `\n       tags:[${c.tags.slice(0, 6).join(", ")}]`,
        )
        .join("\n"),
  );

  return Promise.all(
    top.map(
      async (c): Promise<Track> => ({
        mbid: c.mbid,
        title: c.title,
        artist: c.artist,
        artistMbid: c.artistMbid,
        durationMs: c.durationMs,
        firstReleaseDate: null,
        releases: [],
        streaming: await clients.getStreamingLinks(c.artist, c.title),
        relevanceScore: c.relevanceScore,
        noveltyScore: c.noveltyScore,
      }),
    ),
  );
}

