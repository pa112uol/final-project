import { describe, it, expect } from "vitest";
import {
  normalizeTitle,
  titlesOverlap,
  filterSeeds,
  deduplicateByMbid,
  deduplicateByTitle,
} from "./dedup";
import type { Candidate, Seed } from "./types";

function makeCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    title: "Test Song",
    artist: "Test Artist",
    artistMbid: "artist-mbid-1",
    mbid: "track-mbid-1",
    durationMs: 180000,
    tagWeightSum: 100,
    trackTagScore: 0,
    listenCount: 1000,
    userCount: 500,
    artistListenCount: 0,
    tags: ["rock"],
    ...overrides,
  };
}

describe("normalizeTitle", () => {
  it("strips remaster suffix", () => {
    expect(normalizeTitle("Song - Remastered 2011")).toBe("song");
    expect(normalizeTitle("Song (Remastered)")).toBe("song");
  });

  it("strips live suffix", () => {
    expect(normalizeTitle("Song (Live)")).toBe("song");
    expect(normalizeTitle("Song [Live at Wembley]")).toBe("song");
  });

  it("strips featuring credits", () => {
    expect(normalizeTitle("Song feat. Other Artist")).toBe("song");
    expect(normalizeTitle("Song ft. Other Artist")).toBe("song");
    expect(normalizeTitle("Song featuring Other Artist")).toBe("song");
  });

  it("strips part indicators", () => {
    expect(normalizeTitle("Song, Part 2")).toBe("song");
    expect(normalizeTitle("Song, Pt. II")).toBe("song");
  });

  it("does not strip hyphenated words in the title", () => {
    expect(normalizeTitle("Drive-In Saturday")).toBe("drive-in saturday");
  });

  it("lowercases the result", () => {
    expect(normalizeTitle("MY SONG")).toBe("my song");
  });
});

describe("titlesOverlap", () => {
  it("returns true for identical titles", () => {
    expect(titlesOverlap("song", "song")).toBe(true);
  });

  it("returns true when longer title starts with shorter + delimiter", () => {
    expect(titlesOverlap("song - remastered", "song")).toBe(true);
    expect(titlesOverlap("song (live)", "song")).toBe(true);
    expect(titlesOverlap("song [bonus]", "song")).toBe(true);
  });

  it("returns false for unrelated titles", () => {
    expect(titlesOverlap("song", "other song")).toBe(false);
  });

  it("returns false when longer starts with shorter but no delimiter", () => {
    // "songwriter" starts with "song" but has no space-delimiter
    expect(titlesOverlap("songwriter", "song")).toBe(false);
  });
});

describe("filterSeeds", () => {
  const seeds: Seed[] = [
    { mbid: "s1", title: "Seed Song", artist: "Artist A" },
  ];

  it("removes candidates whose title matches a seed", () => {
    const candidates = [
      makeCandidate({ title: "Seed Song" }),
      makeCandidate({ title: "Other Track", mbid: "mbid-2" }),
    ];
    const result = filterSeeds(candidates, seeds);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Other Track");
  });

  it("removes variant versions of seed titles", () => {
    const candidates = [
      makeCandidate({ title: "Seed Song - Remastered" }),
      makeCandidate({ title: "Unrelated Track", mbid: "mbid-3" }),
    ];
    const result = filterSeeds(candidates, seeds);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Unrelated Track");
  });

  it("is case-insensitive for title matching", () => {
    const candidates = [makeCandidate({ title: "SEED SONG" })];
    expect(filterSeeds(candidates, seeds)).toHaveLength(0);
  });

  it("removes all tracks by the seed artist, not just the exact seed title", () => {
    const candidates = [
      makeCandidate({ title: "Seed Song", artist: "Artist A" }),
      makeCandidate({
        title: "Other Song by Seed Artist",
        artist: "Artist A",
        mbid: "mbid-2",
      }),
      makeCandidate({
        title: "Unrelated Track",
        artist: "Artist B",
        mbid: "mbid-3",
      }),
    ];
    const result = filterSeeds(candidates, seeds);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Unrelated Track");
  });

  it("is case-insensitive for artist matching", () => {
    const candidates = [
      makeCandidate({
        title: "Another Track",
        artist: "artist a",
        mbid: "mbid-2",
      }),
    ];
    expect(filterSeeds(candidates, seeds)).toHaveLength(0);
  });

  it("excludes all tracks by every seed artist in a multi seed scenario", () => {
    const multiSeeds: Seed[] = [
      { mbid: "s1", title: "Song One", artist: "Band One" },
      { mbid: "s2", title: "Song Two", artist: "Band Two" },
    ];
    const candidates = [
      makeCandidate({ title: "Track by Band One", artist: "Band One" }),
      makeCandidate({
        title: "Track by Band Two",
        artist: "Band Two",
        mbid: "mbid-2",
      }),
      makeCandidate({
        title: "Track by Other",
        artist: "Band Three",
        mbid: "mbid-3",
      }),
    ];
    const result = filterSeeds(candidates, multiSeeds);
    expect(result).toHaveLength(1);
    expect(result[0].artist).toBe("Band Three");
  });

  it("still filters same-title tracks from non-seed artists (covers)", () => {
    const candidates = [
      makeCandidate({
        title: "Seed Song",
        artist: "Cover Artist",
        mbid: "mbid-cover",
      }),
      makeCandidate({
        title: "Different Track",
        artist: "Cover Artist",
        mbid: "mbid-2",
      }),
    ];
    const result = filterSeeds(candidates, seeds);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Different Track");
  });

  it("with excludeSeedArtists=false, other tracks by the seed artist are kept", () => {
    const candidates = [
      makeCandidate({ title: "Seed Song", artist: "Artist A" }),
      makeCandidate({
        title: "Other Song by Seed Artist",
        artist: "Artist A",
        mbid: "mbid-2",
      }),
      makeCandidate({
        title: "Unrelated Track",
        artist: "Artist B",
        mbid: "mbid-3",
      }),
    ];
    const result = filterSeeds(candidates, seeds, false);
    expect(result).toHaveLength(2);
    const titles = result.map((c) => c.title);
    expect(titles).toContain("Other Song by Seed Artist");
    expect(titles).toContain("Unrelated Track");
    expect(titles).not.toContain("Seed Song");
  });
});

describe("deduplicateByMbid", () => {
  it("removes duplicate MBIDs, keeping first occurrence", () => {
    const candidates = [
      makeCandidate({ title: "Song A", mbid: "same-mbid", listenCount: 100 }),
      makeCandidate({
        title: "Song A (Live)",
        mbid: "same-mbid",
        listenCount: 200,
      }),
    ];
    const result = deduplicateByMbid(candidates);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Song A");
  });

  it("keeps candidates with empty/falsy MBIDs", () => {
    const candidates = [
      makeCandidate({ title: "No MBID A", mbid: "" }),
      makeCandidate({ title: "No MBID B", mbid: "" }),
    ];
    const result = deduplicateByMbid(candidates);
    expect(result).toHaveLength(2);
  });

  it("does not mutate input array", () => {
    const candidates = [
      makeCandidate({ mbid: "a" }),
      makeCandidate({ mbid: "a" }),
    ];
    const copy = [...candidates];
    deduplicateByMbid(candidates);
    expect(candidates).toHaveLength(copy.length);
  });
});

describe("deduplicateByTitle", () => {
  it("prefers the candidate with an MBID over one without", () => {
    const candidates = [
      makeCandidate({ title: "Song", mbid: "", listenCount: 9999 }),
      makeCandidate({
        title: "Song - Remastered",
        mbid: "real-mbid",
        listenCount: 1,
      }),
    ];
    const result = deduplicateByTitle(candidates);
    expect(result).toHaveLength(1);
    expect(result[0].mbid).toBe("real-mbid");
  });

  it("when both have MBIDs, keeps the one with more listens", () => {
    const candidates = [
      makeCandidate({ title: "Song", mbid: "mbid-a", listenCount: 500 }),
      makeCandidate({
        title: "Song (Live)",
        mbid: "mbid-b",
        listenCount: 2000,
      }),
    ];
    const result = deduplicateByTitle(candidates);
    expect(result).toHaveLength(1);
    expect(result[0].listenCount).toBe(2000);
  });

  it("treats different artists as different entries", () => {
    const candidates = [
      makeCandidate({ title: "Song", artist: "Artist A", mbid: "a1" }),
      makeCandidate({ title: "Song", artist: "Artist B", mbid: "b1" }),
    ];
    expect(deduplicateByTitle(candidates)).toHaveLength(2);
  });

  it("does not mutate the input array", () => {
    const candidates = [
      makeCandidate({ title: "Song", mbid: "mbid-1" }),
      makeCandidate({ title: "Song (Remastered)", mbid: "mbid-2" }),
    ];
    const len = candidates.length;
    deduplicateByTitle(candidates);
    expect(candidates).toHaveLength(len);
  });
});

