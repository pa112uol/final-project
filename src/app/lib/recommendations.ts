import { fetchTrackTags, fetchTagArtists, LFTag } from "@/app/lib/lastfm";
import {
  fetchArtistPopularity,
  fetchArtistTopRecordings,
  fetchRecordingTags,
} from "@/app/lib/listenbrainz";
import { resolveArtistMbid } from "@/app/lib/mb";
import { getStreamingLinks, StreamingLinks } from "@/app/lib/streaming";

const RECOMMENDATION_LIMIT = 10;
// LB tag counts are ~1-10; LF tag counts go up to 100. Scale LB up so they
// dominate TF in buildTagWeights while still letting LF mood/vibe tags supplement.
const LB_TAG_SCALE = 15;
const TOP_TAGS_COUNT = 6;
const ARTISTS_PER_TAG = 30;
const TOP_ARTISTS_COUNT = 15;
const TRACKS_PER_ARTIST = 5;
const MOOD_BOOST_WEIGHT = 1_000;
const MMR_LAMBDA = 0.7;

// Last.fm user-collection tags, describe listening habits, not musical content.
const NOISE_TAGS = new Set([
  "seen live",
  "favorites",
  "favourite",
  "love",
  "awesome",
  "good",
  "amazing",
  "beautiful",
  "cool",
  "songs i like",
  "favourite songs",
  "under 2000 listeners",
  "all",
  "music",
  "epic",
  "glorious",
]);

// Genre roots, compound genre labels one level above sub-genre, and decade tags
// are excluded from candidate fetching they pull in stylistically unrelated
// artists. Only sub-genre and scene tags (e.g. "britpop", "shoegaze") are used.
const BROAD_FETCH_TAGS = new Set([
  "rock",
  "pop",
  "pop rock",
  "alternative",
  "indie",
  "metal",
  "electronic",
  "electronica",
  "folk",
  "jazz",
  "classical",
  "punk",
  "dance",
  "hip hop",
  "r&b",
  "rap",
  "country",
  "soul",
  "blues",
  "reggae",
  "latin",
  "classic rock",
  "alternative rock",
  "indie rock",
  "indie pop",
  // "art rock",
  // "hard rock",
  // "soft rock",
  // "progressive rock",
  "60s",
  "70s",
  "80s",
  "90s",
  "00s",
  "2000s",
  "2010s",
  "2020s",
  "british",
]);

export const MOOD_TAGS: Record<string, string[]> = {
  happy: ["happy", "upbeat", "feel good"],
  sad: ["sad", "melancholic", "emotional"],
  energetic: ["energetic", "hype", "workout"],
  chill: ["chill", "relaxing", "mellow"],
  angry: ["angry", "aggressive", "intense"],
  melancholic: ["melancholic", "bittersweet", "nostalgic"],
  romantic: ["romantic", "love"],
  focus: ["focus", "study", "instrumental"],
};

export interface Seed {
  mbid: string;
  title: string;
  artist: string;
}

export interface Track {
  mbid: string;
  title: string;
  artist: string;
  artistMbid: string;
  durationMs: number | null;
  firstReleaseDate: string | null;
  releases: { mbid: string; title: string; date?: string }[];
  streaming: StreamingLinks;
  relevanceScore: number;
  noveltyScore: number;
}

interface Candidate {
  title: string;
  artist: string;
  artistMbid: string;
  mbid: string;
  durationMs: number | null;
  tagWeightSum: number;
  listenCount: number;
  userCount: number;
  artistListenCount: number;
  tags: string[];
}

interface ScoredCandidate extends Candidate {
  finalScore: number;
  relevanceScore: number;
  noveltyScore: number;
}

function tokenize(tags: string[]): Set<string> {
  const tokens = new Set<string>();
  for (const tag of tags) {
    for (const word of tag.toLowerCase().split(/\s+/)) {
      if (word) tokens.add(word);
    }
  }
  return tokens;
}

function jaccardSets(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const token of a) {
    if (b.has(token)) intersection++;
  }
  return intersection / (a.size + b.size - intersection);
}

function mmrSelect(ranked: ScoredCandidate[], k: number): ScoredCandidate[] {
  const remaining = ranked.map((c) => ({ c, tokens: tokenize(c.tags) }));
  const selected: ScoredCandidate[] = [];
  const selectedTokens: Set<string>[] = [];

  while (selected.length < k && remaining.length > 0) {
    let bestIdx = 0;
    let bestScore = -Infinity;
    for (let i = 0; i < remaining.length; i++) {
      const { c, tokens } = remaining[i];
      const maxSim =
        selectedTokens.length === 0
          ? 0
          : Math.max(...selectedTokens.map((st) => jaccardSets(tokens, st)));
      const score = MMR_LAMBDA * c.finalScore - (1 - MMR_LAMBDA) * maxSim;
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
    selected.push(remaining[bestIdx].c);
    selectedTokens.push(remaining[bestIdx].tokens);
    remaining.splice(bestIdx, 1);
  }
  return selected;
}

function titlesOverlap(a: string, b: string): boolean {
  if (a === b) return true;
  const [longer, shorter] = a.length >= b.length ? [a, b] : [b, a];
  return (
    longer.startsWith(shorter) && /^ [-(\[]/.test(longer.slice(shorter.length))
  );
}

// Strip edition/version suffixes (" - Remastered", " (Live)", " [Bonus Track]")
// so variant recordings of the same song collapse to a single key. A space
// before the delimiter avoids clipping hyphenated titles like "Drive-In".
function normalizeTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/ [-(\[].*$/, "")
    .trim();
}

function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function filterSeeds(
  candidateMap: Map<string, Candidate>,
  seeds: Seed[],
): void {
  const seedTitles = seeds.map((s) => s.title.toLowerCase());
  for (const [key, c] of candidateMap) {
    const ct = c.title.toLowerCase();
    if (seedTitles.some((t) => titlesOverlap(t, ct))) {
      candidateMap.delete(key);
    }
  }
}

function deduplicateByMbid(candidateMap: Map<string, Candidate>): void {
  const seenMbids = new Set<string>();
  for (const [key, c] of candidateMap) {
    if (c.mbid) {
      if (seenMbids.has(c.mbid)) candidateMap.delete(key);
      else seenMbids.add(c.mbid);
    }
  }
}

// Collapse variant recordings (remaster/live/single editions) that share a
// normalized title + artist but carry distinct MBIDs, which deduplicateByMbid
// cannot catch. Keep the variant with an MBID (enables popularity lookup),
// then the one with more listens (tagWeightSum is artist-level and equal for
// all recordings from the same artist, so it cant break ties here)
function deduplicateByTitle(candidateMap: Map<string, Candidate>): void {
  const kept = new Map<string, string>(); // normalized key -> surviving map key
  for (const [key, c] of candidateMap) {
    const normKey = `${normalizeTitle(c.title)}|||${c.artist.toLowerCase()}`;
    const prevKey = kept.get(normKey);
    if (prevKey === undefined) {
      kept.set(normKey, key);
      continue;
    }
    const prev = candidateMap.get(prevKey)!;
    const cWins =
      !!c.mbid !== !!prev.mbid ? !!c.mbid : c.listenCount > prev.listenCount;
    if (cWins) {
      candidateMap.delete(prevKey);
      kept.set(normKey, key);
    } else {
      candidateMap.delete(key);
    }
  }
}

function normalizeTag(tag: string): string {
  return tag.replace(/-/g, " ");
}

function mergeTags(
  lbTags: { name: string; count: number }[],
  lfTags: LFTag[],
): LFTag[] {
  const merged = new Map<string, { count: number; original: string }>();
  for (const { name, count } of lbTags) {
    const norm = normalizeTag(name);
    if (!NOISE_TAGS.has(norm)) {
      const existing = merged.get(norm);
      if (existing) existing.count += count * LB_TAG_SCALE;
      else merged.set(norm, { count: count * LB_TAG_SCALE, original: name });
    }
  }
  // Last.fm supplements with mood/vibe tags absent from LB; if tag is already
  // present from LB, keep the boosted LB weight.
  for (const { name, count } of lfTags) {
    const norm = normalizeTag(name);
    if (!NOISE_TAGS.has(norm) && !merged.has(norm))
      merged.set(norm, { count, original: name });
  }
  return [...merged.values()].map(({ count, original }) => ({
    name: original,
    count,
  }));
}

function buildTagWeights(seedTagSets: LFTag[][]): Map<string, number> {
  const totalSeeds = Math.max(seedTagSets.length, 1);
  const tagTF = new Map<string, number>(); // norm => total count
  const tagDF = new Map<string, number>(); // norm => doc frequency
  const tagOriginal = new Map<string, string>(); // norm => first-seen original form

  for (const tags of seedTagSets) {
    const seenInSeed = new Set<string>();
    for (const { name, count } of tags) {
      const norm = normalizeTag(name);
      tagTF.set(norm, (tagTF.get(norm) ?? 0) + count);
      if (!tagOriginal.has(norm)) tagOriginal.set(norm, name);
      if (!seenInSeed.has(norm)) {
        tagDF.set(norm, (tagDF.get(norm) ?? 0) + 1);
        seenInSeed.add(norm);
      }
    }
  }

  const weights = new Map<string, number>();
  for (const [norm, tf] of tagTF) {
    const df = tagDF.get(norm) ?? 1;
    const idf = Math.log((totalSeeds + 1) / (df + 1)) + 1;
    weights.set(tagOriginal.get(norm)!, tf * idf);
  }

  return weights;
}

async function buildCandidates(
  topTags: [string, number][],
  apiKey: string,
): Promise<Map<string, Candidate>> {
  // Phase A: score artists by how many weighted tags they appear in
  const artistScores = new Map<
    string,
    { name: string; tagWeightSum: number; mbid: string }
  >();
  const artistTags = new Map<string, Set<string>>();

  await Promise.allSettled(
    topTags.map(async ([tag, tagWeight]) => {
      const artists = await fetchTagArtists(tag, 1, ARTISTS_PER_TAG, apiKey);
      for (const artist of artists) {
        const key = artist.name.toLowerCase();
        const existing = artistScores.get(key);
        if (existing) {
          existing.tagWeightSum += tagWeight;
          if (!existing.mbid && artist.mbid) existing.mbid = artist.mbid;
        } else {
          artistScores.set(key, {
            name: artist.name,
            tagWeightSum: tagWeight,
            mbid: artist.mbid ?? "",
          });
        }
        if (!artistTags.has(key)) artistTags.set(key, new Set());
        artistTags.get(key)!.add(tag);
      }
    }),
  );

  const topArtists = [...artistScores.values()]
    .sort(
      (a, b) => b.tagWeightSum - a.tagWeightSum || a.name.localeCompare(b.name),
    )
    .slice(0, TOP_ARTISTS_COUNT);

  console.log(
    "[candidates] top artists:",
    topArtists.map((a) => `${a.name}(${a.tagWeightSum.toFixed(0)})`).join(", "),
  );

  // Resolve missing artist MBIDs via MusicBrainz (serialised by mbFetch queue)
  await Promise.all(
    topArtists
      .filter((a) => !a.mbid)
      .map(async (a) => {
        a.mbid = await resolveArtistMbid(a.name);
        console.log(
          `[candidates] resolved mbid for ${a.name}: ${a.mbid || "not found"}`,
        );
      }),
  );

  // Phase B: fetch top recordings from ListenBrainz: verified MBIDs + listen counts
  const candidates = new Map<string, Candidate>();

  await Promise.all(
    topArtists.map(async (artist) => {
      if (!artist.mbid) return;
      const recordings = await fetchArtistTopRecordings(
        artist.mbid,
        TRACKS_PER_ARTIST,
      );
      const matchedTags = [
        ...(artistTags.get(artist.name.toLowerCase()) ?? []),
      ];
      for (const r of recordings) {
        const key = `${r.title.toLowerCase()}|||${artist.name.toLowerCase()}`;
        candidates.set(key, {
          title: r.title,
          artist: artist.name,
          artistMbid: r.artistMbid,
          mbid: r.mbid,
          durationMs: r.durationMs,
          tagWeightSum: artist.tagWeightSum,
          listenCount: r.listenCount,
          userCount: r.userCount,
          artistListenCount: 0,
          tags: r.tags.length > 0 ? r.tags : matchedTags,
        });
      }
    }),
  );

  return candidates;
}

// Obscurity from a listen count, normalized on a log scale against the max.
// Log scale is essential: listen counts are power-law distributed, so linear
// normalization lets one mega popular track flatten everything else to ~1
function logObscurity(count: number, logMax: number): number {
  if (logMax <= 0) return 0;
  return 1 - Math.log1p(count) / logMax;
}

function scoreAndSort(
  candidates: Candidate[],
  novelty: number,
): ScoredCandidate[] {
  if (candidates.length === 0) return [];
  let maxRelevance = 0, maxListenCount = 1, maxUserCount = 1, maxArtistListenCount = 1;
  for (const c of candidates) {
    if (c.tagWeightSum > maxRelevance) maxRelevance = c.tagWeightSum;
    if (c.listenCount > maxListenCount) maxListenCount = c.listenCount;
    if (c.userCount > maxUserCount) maxUserCount = c.userCount;
    if (c.artistListenCount > maxArtistListenCount) maxArtistListenCount = c.artistListenCount;
  }
  const logMaxListen = Math.log1p(maxListenCount);
  const logMaxUser = Math.log1p(maxUserCount);
  const logMaxArtist = Math.log1p(maxArtistListenCount);

  // First pass: obscurity for candidates that have any popularity data. Recording
  // count is the more specific signal; when both exist, weight it over the
  // artist-level one rather than ignoring whichever branch comes second.
  // Within the recording signal, blend listen count (scale) with user count
  // (breadth) so repeat-play niche hits don't outscore genuinely popular tracks.
  const obscurity = new Map<Candidate, number>();
  const known: number[] = [];
  for (const c of candidates) {
    const hasRec = c.listenCount > 0;
    const hasArt = c.artistListenCount > 0;
    if (!hasRec && !hasArt) continue;
    let recObsc: number | null = null;
    if (hasRec) {
      const listenObsc = logObscurity(c.listenCount, logMaxListen);
      const userObsc =
        c.userCount > 0 ? logObscurity(c.userCount, logMaxUser) : listenObsc;
      recObsc = 0.6 * listenObsc + 0.4 * userObsc;
    }
    const artObsc = hasArt
      ? logObscurity(c.artistListenCount, logMaxArtist)
      : null;
    const o =
      recObsc !== null && artObsc !== null
        ? 0.7 * recObsc + 0.3 * artObsc
        : (recObsc ?? artObsc)!;
    obscurity.set(c, o);
    known.push(o);
  }
  // Tracks with no popularity data get the median observed obscurity, not a
  // hardcoded 0.5. The median places them neutrally within the actual
  // distribution and avoids a large tie-cluster that the novelty slider can't break
  const neutral = known.length > 0 ? median(known) : 0.5;

  return candidates
    .map((c): ScoredCandidate => {
      const relevanceNorm =
        maxRelevance > 0 ? c.tagWeightSum / maxRelevance : 0;
      const popularityObscurity = obscurity.get(c) ?? neutral;
      const finalScore =
        (1 - novelty) * relevanceNorm + novelty * popularityObscurity;
      return {
        ...c,
        finalScore,
        relevanceScore: relevanceNorm,
        noveltyScore: popularityObscurity,
      };
    })
    .sort((a, b) => b.finalScore - a.finalScore);
}

export async function getRecommendations(
  seeds: Seed[],
  apiKey: string,
  mood?: string,
  novelty = 0,
): Promise<Track[]> {
  const seedTagSets = await Promise.all(
    seeds.map(async (s) => {
      const [lbTags, lfTags] = await Promise.all([
        s.mbid ? fetchRecordingTags(s.mbid) : Promise.resolve([]),
        fetchTrackTags(s.title, s.artist, apiKey, s.mbid || undefined),
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
      return mergeTags(lbTags, lfTags);
    }),
  );

  const mergedSummary = seedTagSets.map(
    (tags: LFTag[], i: number) =>
      `  seed[${i}] (${seeds[i].title} – ${seeds[i].artist}): ${tags.map((t: LFTag) => `${t.name}(${t.count})`).join(", ") || "(none)"}`,
  );
  console.log("[tags/merged]\n" + mergedSummary.join("\n"));

  const tagWeights = buildTagWeights(seedTagSets);
  const sortedTags = [...tagWeights.entries()].sort((a, b) => b[1] - a[1]);

  if (sortedTags.length === 0) return [];

  // Exclude tags that match a seed artist name, e.g. "queen" for a Queen seed
  // would make fetchTagArtists return mostly Queen members and collaborators
  const seedArtistNames = new Set(seeds.map((s) => s.artist.toLowerCase()));

  // Prefer specific tags for fetching; fall back to broad ones only when
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

  const candidateMap = new Map(
    [...(await buildCandidates(fetchTags, apiKey)).entries()].sort(([a], [b]) =>
      a.localeCompare(b),
    ),
  );

  filterSeeds(candidateMap, seeds);
  deduplicateByMbid(candidateMap);
  deduplicateByTitle(candidateMap);
  // For tracks with no listen count (listenCount === 0), fall back to artist-level popularity
  const artistMbids = [...candidateMap.values()]
    .filter((c) => c.listenCount === 0 && c.artistMbid)
    .map((c) => c.artistMbid);
  const lbArtistPopularity = await fetchArtistPopularity([
    ...new Set(artistMbids),
  ]);
  for (const candidate of candidateMap.values()) {
    if (candidate.listenCount === 0) {
      const count = lbArtistPopularity.get(candidate.artistMbid);
      if (count !== undefined) candidate.artistListenCount = count;
    }
  }

  if (mood && MOOD_TAGS[mood]) {
    const moodTagSet = new Set(MOOD_TAGS[mood]);
    for (const c of candidateMap.values()) {
      if (c.tags.some((t) => moodTagSet.has(t.toLowerCase()))) {
        c.tagWeightSum += MOOD_BOOST_WEIGHT;
      }
    }
  }

  const artistTrackCount = new Map<string, number>();
  const top = mmrSelect(
    scoreAndSort(
      [...candidateMap.values()].filter((c) => c.mbid),
      novelty,
    ).filter((c) => {
      const key = c.artist.toLowerCase();
      const count = artistTrackCount.get(key) ?? 0;
      if (count >= 2) return false;
      artistTrackCount.set(key, count + 1);
      return true;
    }),
    RECOMMENDATION_LIMIT,
  ).sort(
    (a, b) => b.finalScore - a.finalScore || b.listenCount - a.listenCount,
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
        streaming: await getStreamingLinks(c.artist, c.title),
        relevanceScore: c.relevanceScore,
        noveltyScore: c.noveltyScore,
      }),
    ),
  );
}

