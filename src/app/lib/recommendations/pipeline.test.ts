import { describe, it, expect, vi } from "vitest";
import { runPipeline } from "./pipeline";
import type { PipelineClients, Seed } from "./types";

function makeClients(
  overrides: Partial<PipelineClients> = {},
): PipelineClients {
  return {
    fetchRecordingTags: vi.fn().mockResolvedValue([]),
    fetchTrackTags: vi.fn().mockResolvedValue([
      { name: "shoegaze", count: 80 },
      { name: "dreampop", count: 60 },
    ]),
    fetchTrackTagsOnly: vi.fn().mockResolvedValue([]),
    fetchTagArtists: vi.fn().mockResolvedValue([
      { name: "Slowdive", mbid: "mbid-slowdive" },
      { name: "Ride", mbid: "mbid-ride" },
    ]),
    fetchArtistTopRecordings: vi.fn().mockImplementation((mbid) => {
      const tracks: Record<string, unknown[]> = {
        "mbid-slowdive": [
          {
            mbid: "rec-alison",
            title: "Alison",
            artistMbid: "mbid-slowdive",
            durationMs: 300000,
            listenCount: 50000,
            userCount: 20000,
            tags: ["shoegaze"],
          },
          {
            mbid: "rec-when-sun",
            title: "When the Sun Hits",
            artistMbid: "mbid-slowdive",
            durationMs: 260000,
            listenCount: 40000,
            userCount: 15000,
            tags: ["shoegaze"],
          },
        ],
        "mbid-ride": [
          {
            mbid: "rec-vapour-trail",
            title: "Vapour Trail",
            artistMbid: "mbid-ride",
            durationMs: 240000,
            listenCount: 30000,
            userCount: 10000,
            tags: ["shoegaze"],
          },
        ],
      };
      return Promise.resolve(tracks[mbid] ?? []);
    }),
    resolveArtistMbid: vi.fn().mockResolvedValue(""),
    fetchArtistPopularity: vi.fn().mockResolvedValue(new Map()),
    getStreamingLinks: vi.fn().mockResolvedValue({
      appleMusic: null,
      preview: null,
      youtubeVideoId: null,
      spotify: "https://open.spotify.com/search/test",
    }),
    ...overrides,
  };
}

const TEST_SEED: Seed = {
  mbid: "seed-mbid-1",
  title: "souvlaki space station",
  artist: "slowdive",
};

describe("runPipeline", () => {
  it("returns an array of Track objects", async () => {
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      makeClients(),
    );
    expect(Array.isArray(tracks)).toBe(true);
    for (const t of tracks) {
      expect(t).toHaveProperty("mbid");
      expect(t).toHaveProperty("title");
      expect(t).toHaveProperty("artist");
      expect(t).toHaveProperty("streaming");
      expect(typeof t.relevanceScore).toBe("number");
      expect(typeof t.noveltyScore).toBe("number");
    }
  });

  it("returns empty array when no tags can be derived", async () => {
    const clients = makeClients({
      fetchTrackTags: vi.fn().mockResolvedValue([]),
      fetchRecordingTags: vi.fn().mockResolvedValue([]),
    });
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      clients,
    );
    expect(tracks).toEqual([]);
  });

  it("excludes the seed track itself from results", async () => {
    const clients = makeClients({
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([
        {
          mbid: "seed-track-rec",
          title: "Souvlaki Space Station",
          artistMbid: "mbid-slowdive",
          durationMs: null,
          listenCount: 99999,
          userCount: 50000,
          tags: ["shoegaze"],
        },
        {
          mbid: "rec-alison",
          title: "Alison",
          artistMbid: "mbid-slowdive",
          durationMs: 300000,
          listenCount: 50000,
          userCount: 20000,
          tags: ["shoegaze"],
        },
      ]),
    });
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      clients,
    );
    const titles = tracks.map((t) => t.title.toLowerCase());
    expect(titles).not.toContain("souvlaki space station");
  });

  it("calls getStreamingLinks for each returned track", async () => {
    const getStreamingLinks = vi.fn().mockResolvedValue({
      appleMusic: null,
      preview: null,
      youtubeVideoId: null,
      spotify: "https://open.spotify.com/search/test",
    });
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      makeClients({ getStreamingLinks }),
    );
    expect(getStreamingLinks).toHaveBeenCalledTimes(tracks.length);
  });

  it("applies mood boost - happy candidates outrank equal non-happy ones", async () => {
    const clients = makeClients({
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([
        {
          mbid: "rec-happy",
          title: "Happy Track",
          artistMbid: "mbid-ride",
          durationMs: null,
          listenCount: 100,
          userCount: 50,
          tags: ["happy"],
        },
        {
          mbid: "rec-neutral",
          title: "Neutral Track",
          artistMbid: "mbid-ride",
          durationMs: null,
          listenCount: 100,
          userCount: 50,
          tags: ["shoegaze"],
        },
      ]),
    });
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      "happy",
      0,
      clients,
    );
    const happyIdx = tracks.findIndex((t) => t.mbid === "rec-happy");
    const neutralIdx = tracks.findIndex((t) => t.mbid === "rec-neutral");
    if (happyIdx !== -1 && neutralIdx !== -1) {
      expect(happyIdx).toBeLessThan(neutralIdx);
    }
  });

  it("mood boost fires via LF tags when LB recording tags contain no mood words", async () => {
    // This is the scenario the old tie-break-only logic could NOT handle:
    // LB tags are pure genre labels; mood words come only from LF enrichment.
    const clients = makeClients({
      fetchArtistTopRecordings: vi.fn().mockResolvedValue([
        {
          mbid: "rec-chill",
          title: "Chill Track",
          artistMbid: "mbid-ride",
          durationMs: null,
          listenCount: 100,
          userCount: 50,
          tags: ["shoegaze"], // LB genre tag only - no mood word
        },
        {
          mbid: "rec-other",
          title: "Other Track",
          artistMbid: "mbid-ride",
          durationMs: null,
          listenCount: 100,
          userCount: 50,
          tags: ["shoegaze"], // same LB genre tag
        },
      ]),
      // LF enrichment adds mood tag only for "Chill Track"
      fetchTrackTagsOnly: vi
        .fn()
        .mockImplementation((title: string) =>
          Promise.resolve(
            title === "Chill Track" ? [{ name: "chill", count: 80 }] : [],
          ),
        ),
    });
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      "chill",
      0,
      clients,
    );
    const chillIdx = tracks.findIndex((t) => t.mbid === "rec-chill");
    const otherIdx = tracks.findIndex((t) => t.mbid === "rec-other");
    expect(chillIdx).toBeGreaterThanOrEqual(0);
    expect(otherIdx).toBeGreaterThanOrEqual(0);
    expect(chillIdx).toBeLessThan(otherIdx);
  });

  it("respects novelty=1 by using artist popularity client", async () => {
    const fetchArtistPopularity = vi.fn().mockResolvedValue(new Map());
    await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      1,
      makeClients({ fetchArtistPopularity }),
    );
    expect(fetchArtistPopularity).toHaveBeenCalled();
  });

  it("excludes all tracks by the seed artist by default", async () => {
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      makeClients(),
    );
    const artists = tracks.map((t) => t.artist.toLowerCase());
    expect(artists).not.toContain("slowdive");
  });

  it("allows seed artist tracks when excludeSeedArtists=false", async () => {
    const tracks = await runPipeline(
      [TEST_SEED],
      "fake-api-key",
      undefined,
      0,
      makeClients(),
      false,
    );
    const artists = tracks.map((t) => t.artist.toLowerCase());
    expect(artists).toContain("slowdive");
  });
});

