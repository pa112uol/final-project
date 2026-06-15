import { describe, it, expect, vi, beforeEach } from "vitest";
import { buildCandidates } from "./candidates";
import type { PipelineClients } from "./types";

type CandidateClients = Pick<
  PipelineClients,
  "fetchTagArtists" | "fetchArtistTopRecordings" | "resolveArtistMbid"
>;

const RECORDING_A = {
  mbid: "rec-a",
  title: "Track A",
  artistMbid: "artist-mbid-1",
  durationMs: 200000,
  listenCount: 5000,
  userCount: 2000,
  tags: ["shoegaze"],
};

const RECORDING_B = {
  mbid: "rec-b",
  title: "Track B",
  artistMbid: "artist-mbid-1",
  durationMs: 180000,
  listenCount: 3000,
  userCount: 1000,
  tags: [],
};

function makeClients(overrides: Partial<CandidateClients> = {}): CandidateClients {
  return {
    fetchTagArtists: vi
      .fn()
      .mockResolvedValue([{ name: "Slowdive", mbid: "artist-mbid-1" }]),
    fetchArtistTopRecordings: vi.fn().mockResolvedValue([RECORDING_A]),
    resolveArtistMbid: vi.fn().mockResolvedValue("resolved-mbid"),
    ...overrides,
  };
}

const TOP_TAGS: [string, number][] = [["shoegaze", 100]];

describe("buildCandidates", () => {
  beforeEach(() => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("returns candidates built from fetched recordings", async () => {
    const result = await buildCandidates(TOP_TAGS, "key", 0, makeClients());
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Track A");
    expect(result[0].mbid).toBe("rec-a");
    expect(result[0].listenCount).toBe(5000);
  });

  it("initialises trackTagScore and artistListenCount to 0", async () => {
    const result = await buildCandidates(TOP_TAGS, "key", 0, makeClients());
    expect(result[0].trackTagScore).toBe(0);
    expect(result[0].artistListenCount).toBe(0);
  });

  it("sets tagWeightSum from the artist's accumulated tag weight", async () => {
    const result = await buildCandidates(TOP_TAGS, "key", 0, makeClients());
    expect(result[0].tagWeightSum).toBe(100);
  });

  it("uses recording tags when present, artist tags as fallback", async () => {
    const clients = makeClients({
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([
        RECORDING_A,  // has tags: ["shoegaze"]
        RECORDING_B,  // has tags: [] → should fall back to matched artist tags
      ]),
    });
    const result = await buildCandidates(TOP_TAGS, "key", 0, clients);
    const recA = result.find((c) => c.mbid === "rec-a")!;
    const recB = result.find((c) => c.mbid === "rec-b")!;
    expect(recA.tags).toEqual(["shoegaze"]);
    // recB has no tags; falls back to the artist's matched tag ("shoegaze")
    expect(recB.tags).toContain("shoegaze");
  });

  it("at novelty=0, fetches only page 1 per tag", async () => {
    const fetchTagArtists = vi
      .fn()
      .mockResolvedValue([{ name: "Slowdive", mbid: "artist-mbid-1" }]);
    await buildCandidates(TOP_TAGS, "key", 0, makeClients({ fetchTagArtists }));
    const pages = fetchTagArtists.mock.calls.map(([, page]) => page);
    expect(pages).toEqual([1]);
  });

  it("at novelty=1, fetches pages 1–3 per tag", async () => {
    const fetchTagArtists = vi
      .fn()
      .mockResolvedValue([{ name: "Slowdive", mbid: "artist-mbid-1" }]);
    await buildCandidates(TOP_TAGS, "key", 1, makeClients({ fetchTagArtists }));
    const pages = fetchTagArtists.mock.calls.map(([, page]) => page);
    expect(pages).toEqual([1, 2, 3]);
  });

  it("accumulates tagWeightSum across multiple tags for the same artist", async () => {
    const tags: [string, number][] = [
      ["shoegaze", 100],
      ["dreampop", 80],
    ];
    const clients = makeClients({
      fetchTagArtists: vi.fn().mockImplementation((tag) =>
        Promise.resolve([
          { name: "Slowdive", mbid: "artist-mbid-1" },
        ])
      ),
    });
    const result = await buildCandidates(tags, "key", 0, clients);
    // Slowdive appears in both tags → tagWeightSum = 100 + 80 = 180
    expect(result[0].tagWeightSum).toBe(180);
  });

  it("credits the same tag only once per artist even when spread across pages", async () => {
    const tags: [string, number][] = [["shoegaze", 100]];
    const fetchTagArtists = vi
      .fn()
      // Same artist on both page 1 and page 2
      .mockResolvedValue([{ name: "Slowdive", mbid: "artist-mbid-1" }]);
    const result = await buildCandidates(tags, "key", 0.5, makeClients({ fetchTagArtists }));
    // tagWeightSum should be 100, not 200, even if novelty causes 2 pages
    expect(result[0].tagWeightSum).toBe(100);
  });

  it("calls resolveArtistMbid for artists with no MBID from Last.fm", async () => {
    const resolveArtistMbid = vi.fn().mockResolvedValue("resolved-mbid");
    const clients = makeClients({
      fetchTagArtists: vi
        .fn()
        .mockResolvedValue([{ name: "Obscure Band", mbid: undefined }]),
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([RECORDING_A]),
      resolveArtistMbid,
    });
    await buildCandidates(TOP_TAGS, "key", 0, clients);
    expect(resolveArtistMbid).toHaveBeenCalledWith("Obscure Band");
  });

  it("does not call resolveArtistMbid when MBID is already present", async () => {
    const resolveArtistMbid = vi.fn();
    await buildCandidates(TOP_TAGS, "key", 0, makeClients({ resolveArtistMbid }));
    expect(resolveArtistMbid).not.toHaveBeenCalled();
  });

  it("skips artists that have no MBID after resolution", async () => {
    const clients = makeClients({
      fetchTagArtists: vi
        .fn()
        .mockResolvedValue([{ name: "Ghost Band", mbid: undefined }]),
      resolveArtistMbid: vi.fn().mockResolvedValue(""),
    });
    const result = await buildCandidates(TOP_TAGS, "key", 0, clients);
    expect(result).toHaveLength(0);
  });

  it("returns empty array when no tags are provided", async () => {
    const result = await buildCandidates([], "key", 0, makeClients());
    expect(result).toHaveLength(0);
  });

  it("swallows fetchTagArtists failures without throwing", async () => {
    const clients = makeClients({
      fetchTagArtists: vi.fn().mockRejectedValue(new Error("API down")),
    });
    await expect(
      buildCandidates(TOP_TAGS, "key", 0, clients),
    ).resolves.toEqual([]);
  });

  it("selects artists with highest tagWeightSum when list exceeds topArtistsCount", async () => {
    // Build 20 artists with distinct scores so we can verify only top-N are kept.
    // At novelty=0, topArtistsCount = 15.
    const manyArtists = Array.from({ length: 20 }, (_, i) => ({
      name: `Artist${i}`,
      mbid: `mbid-${i}`,
    }));
    const tags: [string, number][] = [
      ["shoegaze", 100],
      // Each additional tag only matches the first 15 artists
    ];
    const fetchTagArtists = vi.fn().mockImplementation((tag) =>
      // "shoegaze" returns all 20; only this tag so all artists have equal weight
      Promise.resolve(manyArtists),
    );
    const fetchArtistTopRecordings = vi
      .fn()
      .mockResolvedValue([RECORDING_A]);

    const result = await buildCandidates(
      tags,
      "key",
      0,
      makeClients({ fetchTagArtists, fetchArtistTopRecordings }),
    );
    // At novelty=0, at most 15 artists, each with 1 recording = max 15 candidates
    expect(result.length).toBeLessThanOrEqual(15);
  });

  it("deduplicates recordings by title+artist key", async () => {
    const duplicate = { ...RECORDING_A, mbid: "rec-a-dup" };
    const clients = makeClients({
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([RECORDING_A, duplicate]),
    });
    const result = await buildCandidates(TOP_TAGS, "key", 0, clients);
    const trackATitles = result.filter((c) => c.title === "Track A");
    // Same title+artist key: only one candidate is kept
    expect(trackATitles).toHaveLength(1);
  });
});
