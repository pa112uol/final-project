import type { Candidate, ScoredCandidate } from "./types";
import {
  LISTEN_VS_USER_BLEND,
  REC_VS_ARTIST_BLEND,
  ARTIST_VS_TRACK_TAG_BLEND,
} from "./constants";

export function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// Obscurity from a listen count, normalized on a log scale against the max.
// Log scale is essential: listen counts are power-law distributed, so linear
// normalization lets one mega-popular track flatten everything else to ~1.
export function logObscurity(count: number, logMax: number): number {
  if (logMax <= 0) return 0;
  return 1 - Math.log1p(count) / logMax;
}

export function scoreAndSort(
  candidates: Candidate[],
  novelty: number,
): ScoredCandidate[] {
  if (candidates.length === 0) return [];

  let maxRelevance = 0,
    maxTrackTagScore = 0,
    maxListenCount = 1,
    maxUserCount = 1,
    maxArtistListenCount = 1;
  for (const c of candidates) {
    if (c.tagWeightSum > maxRelevance) maxRelevance = c.tagWeightSum;
    if (c.trackTagScore > maxTrackTagScore) maxTrackTagScore = c.trackTagScore;
    if (c.listenCount > maxListenCount) maxListenCount = c.listenCount;
    if (c.userCount > maxUserCount) maxUserCount = c.userCount;
    if (c.artistListenCount > maxArtistListenCount)
      maxArtistListenCount = c.artistListenCount;
  }
  const logMaxListen = Math.log1p(maxListenCount);
  const logMaxUser = Math.log1p(maxUserCount);
  const logMaxArtist = Math.log1p(maxArtistListenCount);

  // First pass: obscurity for candidates with any popularity data. Recording
  // count is the more specific signal. Blend listen count (scale) with user
  // count (breadth) so repeat-play niche hits don't outscore genuinely popular tracks.
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
      recObsc =
        LISTEN_VS_USER_BLEND * listenObsc +
        (1 - LISTEN_VS_USER_BLEND) * userObsc;
    }
    const artObsc = hasArt
      ? logObscurity(c.artistListenCount, logMaxArtist)
      : null;
    const o =
      recObsc !== null && artObsc !== null
        ? REC_VS_ARTIST_BLEND * recObsc + (1 - REC_VS_ARTIST_BLEND) * artObsc
        : (recObsc ?? artObsc)!;
    obscurity.set(c, o);
    known.push(o);
  }
  // Tracks with no popularity data get the median observed obscurity, not a
  // hardcoded 0.5, so they sit neutrally within the actual distribution.
  const neutral = known.length > 0 ? median(known) : 0.5;

  // Compute raw relevance and obscurity before normalizing so we can min-max
  // scale both to [0,1]. Without this, relevance clusters near the top of its
  // range while obscurity spans the full range, making ν=0.5 biased toward relevance.
  const rawScores = candidates.map((c) => {
    const artistNorm = maxRelevance > 0 ? c.tagWeightSum / maxRelevance : 0;
    const trackTagNorm =
      maxTrackTagScore > 0 && c.trackTagScore > 0
        ? c.trackTagScore / maxTrackTagScore
        : artistNorm;
    return {
      c,
      relevance:
        ARTIST_VS_TRACK_TAG_BLEND * artistNorm +
        (1 - ARTIST_VS_TRACK_TAG_BLEND) * trackTagNorm,
      obs: obscurity.get(c) ?? neutral,
    };
  });

  let minRel = Infinity,
    maxRel = -Infinity,
    minObs = Infinity,
    maxObs = -Infinity;
  for (const { relevance, obs } of rawScores) {
    if (relevance < minRel) minRel = relevance;
    if (relevance > maxRel) maxRel = relevance;
    if (obs < minObs) minObs = obs;
    if (obs > maxObs) maxObs = obs;
  }
  const rangeRel = maxRel - minRel || 1;
  const rangeObs = maxObs - minObs || 1;

  return rawScores
    .map(({ c, relevance, obs }): ScoredCandidate => {
      const relevanceNorm = (relevance - minRel) / rangeRel;
      const popularityObscurity = (obs - minObs) / rangeObs;
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

