import type { LFTag } from "./types";
import { LB_TAG_SCALE } from "./constants";

// Last.fm user-collection tags that describe listening habits, not musical content.
export const NOISE_TAGS = new Set([
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
// are excluded from candidate fetching - they pull in stylistically unrelated
// artists. Only sub-genre and scene tags (e.g. "britpop", "shoegaze") are used
export const BROAD_FETCH_TAGS = new Set([
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

export function normalizeTag(tag: string): string {
  return tag.replace(/-/g, " ");
}

// Numeric tags ("-1001740215468") and specific year tags ("2019",
// "1990s") that slip past BROAD_FETCH_TAGS produce useless artist lists from
// tag.getTopArtists
export function isNoiseTag(tag: string): boolean {
  return (
    /^-?\d+$/.test(tag) || // numeric tags: -1001740215468
    /^(19|20)\d{2}s?$/.test(tag) || // full years/decades: 2019, 1990s, 2010s
    /^\d{2}s$/.test(tag) // abbreviated decades: 70s, 80s, 90s
  );
}

export function mergeTags(
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

export function buildTagWeights(seedTagSets: LFTag[][]): Map<string, number> {
  const totalSeeds = Math.max(seedTagSets.length, 1);
  const tagTF = new Map<string, number>();
  const tagDF = new Map<string, number>();
  const tagOriginal = new Map<string, string>();

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

  // Standard IDF rewards rare tags by computing log(N/df), but for preference
  // profiling a tag shared across all seeds is the strongest signal, not noise.
  // Flipping the ratio to log(df/N) makes consensus boost weight rather than suppress it
  const weights = new Map<string, number>();
  for (const [norm, tf] of tagTF) {
    const df = tagDF.get(norm) ?? 1;
    const idf = 1 + Math.log((df + 1) / (totalSeeds + 1));
    weights.set(tagOriginal.get(norm)!, tf * idf);
  }

  return weights;
}

