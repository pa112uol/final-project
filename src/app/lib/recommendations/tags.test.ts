import { describe, it, expect } from "vitest";
import {
  normalizeTag,
  mergeTags,
  buildTagWeights,
  NOISE_TAGS,
  BROAD_FETCH_TAGS,
  MOOD_TAGS,
} from "./tags";

describe("normalizeTag", () => {
  it("replaces hyphens with spaces", () => {
    expect(normalizeTag("post-punk")).toBe("post punk");
    expect(normalizeTag("indie-rock")).toBe("indie rock");
  });

  it("leaves non-hyphen tags unchanged", () => {
    expect(normalizeTag("shoegaze")).toBe("shoegaze");
  });
});

describe("NOISE_TAGS", () => {
  it("contains user-collection noise", () => {
    expect(NOISE_TAGS.has("seen live")).toBe(true);
    expect(NOISE_TAGS.has("favorites")).toBe(true);
  });

  it("does not contain genre tags", () => {
    expect(NOISE_TAGS.has("shoegaze")).toBe(false);
    expect(NOISE_TAGS.has("britpop")).toBe(false);
  });
});

describe("BROAD_FETCH_TAGS", () => {
  it("contains top-level genres", () => {
    expect(BROAD_FETCH_TAGS.has("rock")).toBe(true);
    expect(BROAD_FETCH_TAGS.has("electronic")).toBe(true);
    expect(BROAD_FETCH_TAGS.has("80s")).toBe(true);
  });
});

describe("MOOD_TAGS", () => {
  it("covers all expected moods", () => {
    const expectedMoods = [
      "happy", "sad", "energetic", "chill", "angry", "melancholic", "romantic", "focus",
    ];
    for (const mood of expectedMoods) {
      expect(MOOD_TAGS[mood]).toBeDefined();
      expect(MOOD_TAGS[mood].length).toBeGreaterThan(0);
    }
  });
});

describe("mergeTags", () => {
  it("scales LB tags by LB_TAG_SCALE and keeps them over LF duplicates", () => {
    const lbTags = [{ name: "shoegaze", count: 3 }];
    const lfTags = [{ name: "shoegaze", count: 100 }];
    const result = mergeTags(lbTags, lfTags);
    // LB tag with count 3 gets scaled to 3*15=45, not replaced by LF's 100
    expect(result).toHaveLength(1);
    expect(result[0].count).toBe(45);
  });

  it("includes LF-only tags not present in LB", () => {
    const lbTags = [{ name: "shoegaze", count: 2 }];
    const lfTags = [
      { name: "shoegaze", count: 90 },
      { name: "dreamy", count: 50 },
    ];
    const result = mergeTags(lbTags, lfTags);
    const names = result.map((t) => t.name);
    expect(names).toContain("dreamy");
    expect(result.find((t) => t.name === "dreamy")!.count).toBe(50);
  });

  it("filters noise tags from both sources", () => {
    const lbTags = [{ name: "seen live", count: 5 }];
    const lfTags = [{ name: "favorites", count: 80 }];
    expect(mergeTags(lbTags, lfTags)).toHaveLength(0);
  });

  it("returns empty array when both inputs are empty", () => {
    expect(mergeTags([], [])).toHaveLength(0);
  });
});

describe("buildTagWeights", () => {
  it("returns empty map for empty input", () => {
    expect(buildTagWeights([]).size).toBe(0);
    expect(buildTagWeights([[]]).size).toBe(0);
  });

  it("assigns higher weight to a tag shared across more seeds", () => {
    // shoegaze appears in both seeds so it carries full consensus weight
    // britpop appears only once and is down-weighted as an idiosyncratic tag
    const seedTagSets = [
      [{ name: "shoegaze", count: 10 }, { name: "britpop", count: 10 }],
      [{ name: "shoegaze", count: 10 }],
    ];
    const weights = buildTagWeights(seedTagSets);
    expect(weights.get("shoegaze")!).toBeGreaterThan(weights.get("britpop")!);
  });

  it("boosts a tag that appears in every seed (maximum consensus)", () => {
    // Both tags have identical total TF of 3. With equal raw counts,
    // rock wins because it is shared across all seeds while shoegaze appears only once
    const seedTagSets = [
      [{ name: "rock", count: 1 }, { name: "shoegaze", count: 3 }],
      [{ name: "rock", count: 1 }],
      [{ name: "rock", count: 1 }],
    ];
    const weights = buildTagWeights(seedTagSets);
    const rockWeight = weights.get("rock")!;
    const shoegazeWeight = weights.get("shoegaze")!;
    expect(rockWeight).toBeGreaterThan(shoegazeWeight);
  });

  it("normalizes hyphen variants of the same tag to the same entry", () => {
    // "post-punk" and "post punk" should be treated as the same normalized tag
    const seedTagSets = [
      [{ name: "post-punk", count: 5 }],
      [{ name: "post punk", count: 5 }],
    ];
    const weights = buildTagWeights(seedTagSets);
    // After normalization both resolve to "post punk"; should result in one entry
    expect(weights.size).toBe(1);
  });
});
