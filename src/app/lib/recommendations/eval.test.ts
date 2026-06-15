import { describe, it, expect } from "vitest";
import { buildTagWeights, normalizeTag } from "./tags";
import { scoreAndSort } from "./scoring";
import { mmrSelect, jaccardSets, tokenize } from "./diversify";
import type { Candidate, ScoredCandidate, LFTag } from "./types";

// Fraction of the relevant set that appears in the top k positions
function recallAtK(
  ranked: ScoredCandidate[],
  relevant: Set<string>,
  k: number,
): number {
  if (relevant.size === 0) return 0;
  return (
    ranked.slice(0, k).filter((c) => relevant.has(c.mbid)).length /
    relevant.size
  );
}

// Reciprocal rank of the first relevant result (0 when none appear)
function mrr(ranked: ScoredCandidate[], relevant: Set<string>): number {
  for (let i = 0; i < ranked.length; i++) {
    if (relevant.has(ranked[i].mbid)) return 1 / (i + 1);
  }
  return 0;
}

// Mean pairwise Jaccard distance between tag sets in a list.
// A score of 1 means every pair of results shares no tags
function intralistDiversity(tracks: ScoredCandidate[]): number {
  if (tracks.length < 2) return 0;
  const sets = tracks.map((t) => tokenize(t.tags));
  let total = 0;
  let pairs = 0;
  for (let i = 0; i < sets.length; i++) {
    for (let j = i + 1; j < sets.length; j++) {
      total += 1 - jaccardSets(sets[i], sets[j]);
      pairs++;
    }
  }
  return total / pairs;
}

function applyTrackTagScores(
  candidates: Candidate[],
  tagWeights: Map<string, number>,
): Candidate[] {
  const nw = new Map<string, number>();
  for (const [tag, w] of tagWeights) {
    nw.set(normalizeTag(tag.toLowerCase()), w);
  }
  return candidates.map((c) => ({
    ...c,
    trackTagScore: c.tags.reduce(
      (sum, tag) => sum + (nw.get(normalizeTag(tag.toLowerCase())) ?? 0),
      0,
    ),
  }));
}

// Two shoegaze and dreampop seed tag profiles used across all evaluation sessions
const SEED_TAG_SETS: LFTag[][] = [
  [
    { name: "shoegaze", count: 100 },
    { name: "dreampop", count: 60 },
    { name: "noise pop", count: 30 },
  ],
  [
    { name: "shoegaze", count: 90 },
    { name: "dreampop", count: 50 },
    { name: "indie", count: 40 },
  ],
];

// Four genre matching candidates and three unrelated distractors.
// tagWeightSum represents expected artist coverage scores from buildCandidates
const CANDIDATE_POOL: Candidate[] = [
  { mbid: "c1", title: "Alison", artist: "Slowdive", artistMbid: "a1", durationMs: 300000, tagWeightSum: 150, trackTagScore: 0, listenCount: 50000, userCount: 20000, artistListenCount: 0, tags: ["shoegaze", "dreampop"] },
  { mbid: "c2", title: "When the Sun Hits", artist: "Slowdive", artistMbid: "a1", durationMs: 260000, tagWeightSum: 140, trackTagScore: 0, listenCount: 40000, userCount: 15000, artistListenCount: 0, tags: ["shoegaze", "noise pop"] },
  { mbid: "c3", title: "Vapour Trail", artist: "Ride", artistMbid: "a2", durationMs: 240000, tagWeightSum: 130, trackTagScore: 0, listenCount: 30000, userCount: 10000, artistListenCount: 0, tags: ["shoegaze", "dreampop"] },
  { mbid: "c4", title: "Heaven or Las Vegas", artist: "Cocteau Twins", artistMbid: "a3", durationMs: 280000, tagWeightSum: 120, trackTagScore: 0, listenCount: 25000, userCount: 8000, artistListenCount: 0, tags: ["dreampop", "shoegaze"] },
  { mbid: "d1", title: "GOAT", artist: "Drake", artistMbid: "a10", durationMs: 200000, tagWeightSum: 10, trackTagScore: 0, listenCount: 5000000, userCount: 2000000, artistListenCount: 0, tags: ["hip hop", "rap", "trap"] },
  { mbid: "d2", title: "Blinding Lights", artist: "The Weeknd", artistMbid: "a11", durationMs: 200000, tagWeightSum: 10, trackTagScore: 0, listenCount: 8000000, userCount: 3000000, artistListenCount: 0, tags: ["pop", "synth pop"] },
  { mbid: "d3", title: "Country Roads", artist: "John Denver", artistMbid: "a12", durationMs: 200000, tagWeightSum: 5, trackTagScore: 0, listenCount: 2000000, userCount: 800000, artistListenCount: 0, tags: ["country", "folk"] },
];

const RELEVANT = new Set(["c1", "c2", "c3", "c4"]);

// Three tracks per cluster with identical tags and descending finalScores.
// Greedy top 3 picks all of cluster A giving ILD of 0
function makeCluster(
  prefix: string,
  tags: string[],
  baseScore: number,
  n: number,
): ScoredCandidate[] {
  return Array.from({ length: n }, (_, i) => ({
    mbid: `${prefix}${i + 1}`,
    title: `Track ${prefix}${i + 1}`,
    artist: `Artist ${prefix}`,
    artistMbid: `art-${prefix}`,
    durationMs: null,
    tagWeightSum: 0,
    trackTagScore: 0,
    listenCount: 0,
    userCount: 0,
    artistListenCount: 0,
    tags,
    finalScore: baseScore - i * 0.05,
    relevanceScore: baseScore - i * 0.05,
    noveltyScore: 0.5,
  }));
}

describe("Recommendation evaluation harness", () => {
  function rankedPool(novelty: number): ScoredCandidate[] {
    const tagWeights = buildTagWeights(SEED_TAG_SETS);
    return scoreAndSort(applyTrackTagScores(CANDIDATE_POOL, tagWeights), novelty);
  }

  describe("recall and ranking", () => {
    it("recall@4 is 1 at novelty=0: all four relevant candidates rank above the three distractors", () => {
      expect(recallAtK(rankedPool(0), RELEVANT, 4)).toBe(1);
    });

    it("MRR is 1 at novelty=0: a relevant candidate occupies rank 1", () => {
      expect(mrr(rankedPool(0), RELEVANT)).toBe(1);
    });

    it("recall@4 is 1 at novelty=1: genre match outweighs the listen count advantage of mainstream distractors", () => {
      expect(recallAtK(rankedPool(1), RELEVANT, 4)).toBe(1);
    });
  });

  describe("leave one out stability", () => {
    it("recall@4 remains 1 after removing one seed from the profile", () => {
      // Simulates a user providing only a single seed rather than two
      const tagWeights = buildTagWeights([SEED_TAG_SETS[1]]);
      const ranked = scoreAndSort(
        applyTrackTagScores(CANDIDATE_POOL, tagWeights),
        0,
      );
      expect(recallAtK(ranked, RELEVANT, 4)).toBe(1);
    });
  });

  describe("novelty parameter effect", () => {
    const popularRelevant: Candidate = {
      mbid: "pop", title: "Popular Track", artist: "Famous Band",
      artistMbid: "ap", durationMs: null, tagWeightSum: 150, trackTagScore: 0,
      listenCount: 10_000_000, userCount: 5_000_000, artistListenCount: 0,
      tags: ["shoegaze", "dreampop"],
    };
    const obscureRelevant: Candidate = {
      mbid: "obs", title: "Obscure Track", artist: "Unknown Band",
      artistMbid: "ao", durationMs: null, tagWeightSum: 80, trackTagScore: 0,
      listenCount: 500, userCount: 200, artistListenCount: 0,
      tags: ["shoegaze", "dreampop"],
    };

    it("at novelty=0 the more relevant candidate ranks above the more obscure one", () => {
      const tagWeights = buildTagWeights(SEED_TAG_SETS);
      const pool = applyTrackTagScores([popularRelevant, obscureRelevant], tagWeights);
      expect(scoreAndSort(pool, 0)[0].mbid).toBe("pop");
    });

    it("at novelty=1 the more obscure candidate ranks above the more popular one", () => {
      const tagWeights = buildTagWeights(SEED_TAG_SETS);
      const pool = applyTrackTagScores([popularRelevant, obscureRelevant], tagWeights);
      expect(scoreAndSort(pool, 1)[0].mbid).toBe("obs");
    });
  });

  describe("MMR diversity", () => {
    it("mmrSelect produces higher intra-list diversity than greedy top k", () => {
      const clusterA = makeCluster("A", ["shoegaze", "dreampop"], 0.9, 3);
      const clusterB = makeCluster("B", ["post punk", "gothic"], 0.75, 3);
      const ranked = [...clusterA, ...clusterB].sort(
        (a, b) => b.finalScore - a.finalScore,
      );
      const greedyTop3 = ranked.slice(0, 3);
      const mmrTop3 = mmrSelect(ranked, 3);
      expect(intralistDiversity(mmrTop3)).toBeGreaterThan(
        intralistDiversity(greedyTop3),
      );
    });

    it("mmrSelect always selects the highest scoring candidate first", () => {
      const clusterA = makeCluster("A", ["shoegaze", "dreampop"], 0.9, 3);
      const clusterB = makeCluster("B", ["post punk", "gothic"], 0.75, 3);
      const ranked = [...clusterA, ...clusterB].sort(
        (a, b) => b.finalScore - a.finalScore,
      );
      expect(mmrSelect(ranked, 4)[0].mbid).toBe("A1");
    });
  });
});
