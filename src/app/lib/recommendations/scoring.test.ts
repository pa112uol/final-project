import { describe, it, expect } from "vitest";
import { median, logObscurity, scoreAndSort } from "./scoring";
import type { Candidate } from "./types";

function makeCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    title: "Track",
    artist: "Artist",
    artistMbid: "artist-mbid",
    mbid: "track-mbid",
    durationMs: null,
    tagWeightSum: 100,
    trackTagScore: 0,
    listenCount: 0,
    userCount: 0,
    artistListenCount: 0,
    tags: [],
    ...overrides,
  };
}

describe("median", () => {
  it("returns middle value for odd-length array", () => {
    expect(median([1, 3, 5])).toBe(3);
    expect(median([5, 1, 3])).toBe(3);
  });

  it("returns average of two middle values for even-length array", () => {
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  it("returns the single value for a one-element array", () => {
    expect(median([7])).toBe(7);
  });

  it("does not mutate the input array", () => {
    const arr = [3, 1, 2];
    median(arr);
    expect(arr).toEqual([3, 1, 2]);
  });
});

describe("logObscurity", () => {
  it("returns 0 when logMax is 0 or negative", () => {
    expect(logObscurity(100, 0)).toBe(0);
    expect(logObscurity(100, -1)).toBe(0);
  });

  it("returns 1 for a count of 0 (maximum obscurity)", () => {
    const logMax = Math.log1p(1_000_000);
    expect(logObscurity(0, logMax)).toBe(1);
  });

  it("returns 0 for max count (minimum obscurity)", () => {
    const maxCount = 1_000_000;
    const logMax = Math.log1p(maxCount);
    expect(logObscurity(maxCount, logMax)).toBeCloseTo(0);
  });

  it("returns value between 0 and 1 for intermediate counts", () => {
    const logMax = Math.log1p(1_000_000);
    const obs = logObscurity(1000, logMax);
    expect(obs).toBeGreaterThan(0);
    expect(obs).toBeLessThan(1);
  });
});

describe("scoreAndSort", () => {
  it("returns empty array for empty input", () => {
    expect(scoreAndSort([], 0)).toEqual([]);
  });

  it("normalizes finalScore to [0,1] range for a single candidate", () => {
    const result = scoreAndSort([makeCandidate({ tagWeightSum: 50 })], 0);
    expect(result[0].finalScore).toBeGreaterThanOrEqual(0);
    expect(result[0].finalScore).toBeLessThanOrEqual(1);
  });

  it("sorts by descending finalScore", () => {
    const candidates = [
      makeCandidate({ tagWeightSum: 10, mbid: "a" }),
      makeCandidate({ tagWeightSum: 100, mbid: "b" }),
      makeCandidate({ tagWeightSum: 50, mbid: "c" }),
    ];
    const result = scoreAndSort(candidates, 0);
    for (let i = 0; i < result.length - 1; i++) {
      expect(result[i].finalScore).toBeGreaterThanOrEqual(
        result[i + 1].finalScore,
      );
    }
  });

  it("at novelty=0, higher tagWeightSum wins", () => {
    const low = makeCandidate({ tagWeightSum: 10, listenCount: 0, mbid: "a" });
    const high = makeCandidate({
      tagWeightSum: 100,
      listenCount: 0,
      mbid: "b",
    });
    const result = scoreAndSort([low, high], 0);
    expect(result[0].mbid).toBe("b");
  });

  it("at novelty=1, more obscure (fewer listens) candidate scores higher", () => {
    // c1 has huge listen count (popular), c2 has tiny listen count (obscure)
    const popular = makeCandidate({
      tagWeightSum: 100,
      listenCount: 1_000_000,
      userCount: 500_000,
      mbid: "popular",
    });
    const obscure = makeCandidate({
      tagWeightSum: 100,
      listenCount: 10,
      userCount: 5,
      mbid: "obscure",
    });
    const result = scoreAndSort([popular, obscure], 1);
    expect(result[0].mbid).toBe("obscure");
  });

  it("assigns neutral obscurity to candidates with no popularity data", () => {
    // Two known candidates bracket the obscurity range. Unknown gets median of
    // their obscurity values after normalization - strictly between 0 and 1.
    const popular = makeCandidate({
      listenCount: 1_000_000,
      userCount: 500_000,
      mbid: "popular",
    });
    const niche = makeCandidate({
      listenCount: 1_000,
      userCount: 500,
      mbid: "niche",
    });
    const unknown = makeCandidate({
      listenCount: 0,
      artistListenCount: 0,
      mbid: "unknown",
    });
    const result = scoreAndSort([popular, niche, unknown], 0.5);
    const unknownResult = result.find((r) => r.mbid === "unknown")!;
    // Neutral median lands strictly between the min and max after normalization
    expect(unknownResult.noveltyScore).toBeGreaterThan(0);
    expect(unknownResult.noveltyScore).toBeLessThan(1);
  });

  it("attaches relevanceScore and noveltyScore to each result", () => {
    const result = scoreAndSort([makeCandidate()], 0.5);
    expect(typeof result[0].relevanceScore).toBe("number");
    expect(typeof result[0].noveltyScore).toBe("number");
  });
});

