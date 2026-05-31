import {
  fetchArtistTopTracks,
  fetchSeedTags,
  fetchTagArtists,
  LFTag,
} from "@/app/lib/lastfm";
import {
  fetchArtistPopularity,
  fetchRecordingPopularity,
} from "@/app/lib/listenbrainz";
import { getStreamingLinks, StreamingLinks } from "@/app/lib/streaming";
const RECOMMENDATION_LIMIT = 10;
const TOP_TAGS_COUNT = 3;
const ARTISTS_PER_TAG = 30;
const TOP_ARTISTS_COUNT = 15;
const TRACKS_PER_ARTIST = 5;
const MOOD_BOOST_WEIGHT = 1_000;

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
}

interface Candidate {
  title: string;
  artist: string;
  artistMbid: string;
  mbid: string;
  durationMs: number | null;
  tagWeightSum: number;
  rankSum: number;
  occurrences: number;
  listenCount: number;
  artistListenCount: number;
}

interface ScoredCandidate extends Candidate {
  finalScore: number;
}

function buildTagWeights(
  seedTagSets: LFTag[][],
  mood?: string,
): Map<string, number> {
  const totalSeeds = Math.max(seedTagSets.length, 1);
  const tagTF = new Map<string, number>();
  const tagDF = new Map<string, number>();

  for (const tags of seedTagSets) {
    const seenInSeed = new Set<string>();
    for (const { name, count } of tags) {
      tagTF.set(name, (tagTF.get(name) ?? 0) + count);
      if (!seenInSeed.has(name)) {
        tagDF.set(name, (tagDF.get(name) ?? 0) + 1);
        seenInSeed.add(name);
      }
    }
  }

  const weights = new Map<string, number>();
  for (const [tag, tf] of tagTF) {
    const df = tagDF.get(tag) ?? 1;
    const idf = Math.log((totalSeeds + 1) / (df + 1)) + 1;
    weights.set(tag, tf * idf);
  }

  if (mood && MOOD_TAGS[mood]) {
    for (const tag of MOOD_TAGS[mood]) {
      weights.set(tag, MOOD_BOOST_WEIGHT);
    }
  }

  return weights;
}

async function buildCandidates(
  topTags: [string, number][],
  page: number,
  apiKey: string,
): Promise<Map<string, Candidate>> {
  // Phase A: score artists by how many weighted tags they appear in
  const artistScores = new Map<
    string,
    { name: string; tagWeightSum: number }
  >();

  await Promise.all(
    topTags.map(async ([tag, tagWeight]) => {
      const artists = await fetchTagArtists(tag, page, ARTISTS_PER_TAG, apiKey);
      for (const artist of artists) {
        const key = artist.name.toLowerCase();
        const existing = artistScores.get(key);
        if (existing) {
          existing.tagWeightSum += tagWeight;
        } else {
          artistScores.set(key, { name: artist.name, tagWeightSum: tagWeight });
        }
      }
    }),
  );

  const topArtists = [...artistScores.values()]
    .sort((a, b) => b.tagWeightSum - a.tagWeightSum)
    .slice(0, TOP_ARTISTS_COUNT);

  console.log(
    "[candidates] top artists:",
    topArtists.map((a) => `${a.name}(${a.tagWeightSum.toFixed(0)})`).join(", "),
  );

  // Phase B: fetch top tracks for each qualifying artist
  const candidates = new Map<string, Candidate>();

  await Promise.all(
    topArtists.map(async (artist) => {
      const tracks = await fetchArtistTopTracks(
        artist.name,
        TRACKS_PER_ARTIST,
        apiKey,
      );
      for (const [idx, t] of tracks.entries()) {
        const key = `${t.name.toLowerCase()}|||${artist.name.toLowerCase()}`;
        candidates.set(key, {
          title: t.name,
          artist: artist.name,
          artistMbid: t.artist?.mbid ?? "",
          mbid: t.mbid ?? "",
          durationMs: t.duration ? Number(t.duration) * 1000 : null,
          tagWeightSum: artist.tagWeightSum,
          rankSum: idx + 1,
          occurrences: 1,
          listenCount: 0,
          artistListenCount: 0,
        });
      }
    }),
  );

  return candidates;
}

function scoreAndSort(
  candidates: Candidate[],
  novelty: number,
): ScoredCandidate[] {
  if (candidates.length === 0) return [];
  const maxRelevance = Math.max(...candidates.map((c) => c.tagWeightSum));
  const maxOccurrences = Math.max(...candidates.map((c) => c.occurrences));
  const maxListenCount = Math.max(...candidates.map((c) => c.listenCount), 1);
  const maxArtistListenCount = Math.max(
    ...candidates.map((c) => c.artistListenCount),
    1,
  );

  return candidates
    .map((c): ScoredCandidate => {
      const relevanceNorm =
        maxRelevance > 0 ? c.tagWeightSum / maxRelevance : 0;
      // Three-tier popularity signal: recording count → artist count → neutral 0.5.
      // 0.5 neutral avoids making a famous band look obscure just because Last.fm
      // omitted its MBID and neither LB endpoint had data for it.
      const popularityObscurity =
        c.listenCount > 0
          ? 1 - c.listenCount / maxListenCount
          : c.artistListenCount > 0
            ? 1 - c.artistListenCount / maxArtistListenCount
            : 0.5;
      const rarityObscurity =
        maxOccurrences > 1 ? 1 - (c.occurrences - 1) / (maxOccurrences - 1) : 1;
      // Multiplicative: a track must be BOTH relatively unknown AND rare across tags.
      // Additive would let cross-tag rarity compensate for high listen counts.
      const noveltyScore = popularityObscurity * rarityObscurity;
      // At novelty=0: sort purely by relevance.
      // At novelty=0.5: novelty acts as a soft popularity penalty on the relevance term.
      // At novelty=1: sort purely by obscurity.
      const finalScore =
        (1 - novelty) * relevanceNorm * (1 - novelty * noveltyScore) +
        novelty * noveltyScore;
      return { ...c, finalScore };
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
    seeds.map((s) =>
      fetchSeedTags(s.title, s.artist, apiKey, s.mbid || undefined),
    ),
  );

  const lfTagsSummary = seedTagSets.map(
    (tags: LFTag[], i: number) =>
      `  seed[${i}] (${seeds[i].title} – ${seeds[i].artist}): ${tags.map((t: LFTag) => `${t.name}(${t.count})`).join(", ") || "(none)"}`,
  );
  console.log("[tags] lastfm track.getTopTags\n" + lfTagsSummary.join("\n"));

  const tagWeights = buildTagWeights(seedTagSets, mood);

  const topTags = [...tagWeights.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_TAGS_COUNT);

  if (topTags.length === 0) return [];

  const page = novelty < 0.34 ? 1 : novelty < 0.67 ? 2 : 3;
  const candidateMap = await buildCandidates(topTags, page, apiKey);

  const seedArtists = new Set(seeds.map((s) => s.artist.toLowerCase()));
  for (const [key, c] of candidateMap) {
    if (seedArtists.has(c.artist.toLowerCase())) candidateMap.delete(key);
  }

  const mbids = [...candidateMap.values()].map((c) => c.mbid).filter(Boolean);
  const lbPopularity = await fetchRecordingPopularity(mbids);
  for (const candidate of candidateMap.values()) {
    const count = lbPopularity.get(candidate.mbid);
    if (count !== undefined) candidate.listenCount = count;
  }

  // For tracks that got no recording-level data, fall back to artist-level popularity.
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

  const artistTrackCount = new Map<string, number>();
  const top = scoreAndSort([...candidateMap.values()], novelty)
    .filter((c) => {
      const key = c.artist.toLowerCase();
      const count = artistTrackCount.get(key) ?? 0;
      if (count >= 1) return false;
      artistTrackCount.set(key, count + 1);
      return true;
    })
    .slice(0, RECOMMENDATION_LIMIT);

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
      }),
    ),
  );
}

