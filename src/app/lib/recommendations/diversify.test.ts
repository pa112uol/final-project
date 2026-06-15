import { describe, it, expect } from "vitest";
import { tokenize, jaccardSets, mmrSelect } from "./diversify";
import type { ScoredCandidate } from "./types";

function makeScoredCandidate(
  overrides: Partial<ScoredCandidate> = {},
): ScoredCandidate {
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
    finalScore: 0.5,
    relevanceScore: 0.5,
    noveltyScore: 0.5,
    ...overrides,
  };
}

describe("tokenize", () => {
  it("splits multi-word tags into individual tokens", () => {
    const tokens = tokenize(["indie rock", "post punk"]);
    expect(tokens.has("indie")).toBe(true);
    expect(tokens.has("rock")).toBe(true);
    expect(tokens.has("post")).toBe(true);
    expect(tokens.has("punk")).toBe(true);
  });

  it("lowercases all tokens", () => {
    const tokens = tokenize(["Shoegaze", "BRITPOP"]);
    expect(tokens.has("shoegaze")).toBe(true);
    expect(tokens.has("britpop")).toBe(true);
  });

  it("deduplicates tokens across tags", () => {
    const tokens = tokenize(["indie rock", "indie pop"]);
    // "indie" appears twice across tags but should be one token
    expect([...tokens].filter((t) => t === "indie")).toHaveLength(1);
  });

  it("returns empty set for empty input", () => {
    expect(tokenize([])).toEqual(new Set());
    expect(tokenize([""])).toEqual(new Set());
  });
});

describe("jaccardSets", () => {
  it("returns 0 when either set is empty", () => {
    expect(jaccardSets(new Set(["a"]), new Set())).toBe(0);
    expect(jaccardSets(new Set(), new Set(["a"]))).toBe(0);
  });

  it("returns 1 for identical sets", () => {
    const s = new Set(["rock", "indie"]);
    expect(jaccardSets(s, s)).toBe(1);
  });

  it("returns 0 for completely disjoint sets", () => {
    expect(jaccardSets(new Set(["a", "b"]), new Set(["c", "d"]))).toBe(0);
  });

  it("returns correct value for partial overlap", () => {
    // intersection = {b}, union = {a,b,c,d} → 1/4 = 0.25
    const result = jaccardSets(new Set(["a", "b"]), new Set(["b", "c", "d"]));
    expect(result).toBeCloseTo(1 / 4);
  });
});

describe("mmrSelect", () => {
  it("returns at most k candidates", () => {
    const ranked = Array.from({ length: 10 }, (_, i) =>
      makeScoredCandidate({ mbid: `mbid-${i}`, finalScore: 1 - i * 0.1 }),
    );
    expect(mmrSelect(ranked, 5)).toHaveLength(5);
  });

  it("returns all candidates when k >= ranked.length", () => {
    const ranked = [
      makeScoredCandidate({ mbid: "a" }),
      makeScoredCandidate({ mbid: "b" }),
    ];
    expect(mmrSelect(ranked, 10)).toHaveLength(2);
  });

  it("returns empty array for empty input", () => {
    expect(mmrSelect([], 5)).toEqual([]);
  });

  it("selects highest-scoring candidate first", () => {
    const ranked = [
      makeScoredCandidate({ mbid: "best", finalScore: 0.9, tags: ["rock"] }),
      makeScoredCandidate({ mbid: "second", finalScore: 0.5, tags: ["rock"] }),
      makeScoredCandidate({ mbid: "third", finalScore: 0.1, tags: ["rock"] }),
    ];
    const result = mmrSelect(ranked, 3);
    expect(result[0].mbid).toBe("best");
  });

  it("penalizes candidates with similar tags to already-selected ones", () => {
    // "copy" has the same tags as "best" and should be deprioritized vs "diverse"
    const ranked = [
      makeScoredCandidate({ mbid: "best", finalScore: 0.9, tags: ["shoegaze", "dreampop"] }),
      makeScoredCandidate({ mbid: "copy", finalScore: 0.85, tags: ["shoegaze", "dreampop"] }),
      makeScoredCandidate({ mbid: "diverse", finalScore: 0.8, tags: ["techno", "electronic"] }),
    ];
    const result = mmrSelect(ranked, 2);
    expect(result[0].mbid).toBe("best");
    // The second pick should prefer "diverse" over "copy" due to MMR penalty
    expect(result[1].mbid).toBe("diverse");
  });
});
