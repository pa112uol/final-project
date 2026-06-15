import type { Candidate, Seed } from "./types";

// Strip edition/version suffixes (" - Remastered", " (Live)", " [Bonus Track]"),
// featuring credits (" feat. X", " ft. X", " featuring X"), and part indicators
// (", Part 2", ", Pt. II") so variant recordings collapse to a single dedup key.
// Space before the delimiter avoids clipping hyphenated titles like "Drive-In".
// Requiring a dot for bare "ft" avoids false positives like "12 sq ft room".
export function normalizeTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/ [-(\[].*$/, "")
    .replace(/ (feat\.?|ft\.|featuring)\s.*$/, "")
    .replace(/,?\s+(part|pt\.?)\s+\w+$/, "")
    .trim();
}

export function titlesOverlap(a: string, b: string): boolean {
  if (a === b) return true;
  const [longer, shorter] = a.length >= b.length ? [a, b] : [b, a];
  return (
    longer.startsWith(shorter) && /^ [-(\[]/.test(longer.slice(shorter.length))
  );
}

export function filterSeeds(
  candidates: Candidate[],
  seeds: Seed[],
  excludeSeedArtists = true,
): Candidate[] {
  const seedArtists = new Set(seeds.map((s) => s.artist.toLowerCase()));
  const seedTitles = seeds.map((s) => s.title.toLowerCase());
  return candidates.filter((c) => {
    if (excludeSeedArtists && seedArtists.has(c.artist.toLowerCase()))
      return false;
    const ct = c.title.toLowerCase();
    return !seedTitles.some((t) => titlesOverlap(t, ct));
  });
}

export function deduplicateByMbid(candidates: Candidate[]): Candidate[] {
  const seenMbids = new Set<string>();
  return candidates.filter((c) => {
    if (!c.mbid) return true;
    if (seenMbids.has(c.mbid)) return false;
    seenMbids.add(c.mbid);
    return true;
  });
}

// Collapse variant recordings (remaster/live/single editions) that share a
// normalized title + artist but carry distinct MBIDs, which deduplicateByMbid
// cannot catch. Keep the variant with an MBID (enables popularity lookup),
// then the one with more listens
export function deduplicateByTitle(candidates: Candidate[]): Candidate[] {
  const kept = new Map<string, Candidate>();
  for (const c of candidates) {
    const normKey = `${normalizeTitle(c.title)}|||${c.artist.toLowerCase()}`;
    const prev = kept.get(normKey);
    if (prev === undefined) {
      kept.set(normKey, c);
      continue;
    }
    const cWins =
      !!c.mbid !== !!prev.mbid ? !!c.mbid : c.listenCount > prev.listenCount;
    if (cWins) kept.set(normKey, c);
  }
  return [...kept.values()];
}

