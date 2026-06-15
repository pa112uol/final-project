import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchArtistTopRecordings } from "./listenbrainz";

const MBID = "test-artist-mbid";
const LIMIT = 5;

const RECORDING_PAYLOAD = [
  {
    recording_mbid: "rec-1",
    recording_name: "Track One",
    artist_mbids: [MBID],
    length: 200000,
    total_listen_count: 10000,
    total_user_count: 5000,
    tags: [{ tag: "trip-hop", count: 10 }],
  },
];

function makeOkResponse(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status: 200 }),
  );
}

function make429Response() {
  return Promise.resolve(new Response(null, { status: 429 }));
}

describe("fetchArtistTopRecordings", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("returns mapped recordings on a successful response", async () => {
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      makeOkResponse(RECORDING_PAYLOAD),
    );
    const results = await fetchArtistTopRecordings(MBID, LIMIT);
    expect(results).toHaveLength(1);
    expect(results[0].mbid).toBe("rec-1");
    expect(results[0].title).toBe("Track One");
    expect(results[0].listenCount).toBe(10000);
    expect(results[0].tags).toEqual(["trip-hop"]);
  });

  it("retries once after a 429 and returns results from the second attempt", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockReturnValueOnce(make429Response())
      .mockReturnValueOnce(makeOkResponse(RECORDING_PAYLOAD));

    const promise = fetchArtistTopRecordings(MBID, LIMIT);
    // Advance past the 500ms retry delay
    await vi.advanceTimersByTimeAsync(500);
    const results = await promise;

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(results).toHaveLength(1);
    expect(results[0].mbid).toBe("rec-1");
  });

  it("returns empty array when both attempts return 429", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockReturnValue(make429Response());

    const promise = fetchArtistTopRecordings(MBID, LIMIT);
    await vi.advanceTimersByTimeAsync(500);
    const results = await promise;

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(results).toEqual([]);
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("429"),
    );
  });

  it("returns empty array on non-429 error status without retrying", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockReturnValueOnce(
        Promise.resolve(new Response(null, { status: 500 })),
      );
    const results = await fetchArtistTopRecordings(MBID, LIMIT);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(results).toEqual([]);
  });

  it("returns empty array when fetch throws", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new Error("network error"),
    );
    const results = await fetchArtistTopRecordings(MBID, LIMIT);
    expect(results).toEqual([]);
  });

  it("respects the limit parameter", async () => {
    const payload = Array.from({ length: 10 }, (_, i) => ({
      recording_mbid: `rec-${i}`,
      recording_name: `Track ${i}`,
      artist_mbids: [MBID],
      length: 200000,
      total_listen_count: 1000,
      total_user_count: 500,
    }));
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(makeOkResponse(payload));
    const results = await fetchArtistTopRecordings(MBID, 3);
    expect(results).toHaveLength(3);
  });

  it("filters out recordings missing required fields", async () => {
    const payload = [
      ...RECORDING_PAYLOAD,
      { recording_mbid: "", recording_name: "No MBID", artist_mbids: [MBID], length: null, total_listen_count: 0, total_user_count: 0 },
      { recording_mbid: "rec-2", recording_name: "", artist_mbids: [MBID], length: null, total_listen_count: 0, total_user_count: 0 },
    ];
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(makeOkResponse(payload));
    const results = await fetchArtistTopRecordings(MBID, LIMIT);
    expect(results).toHaveLength(1);
    expect(results[0].mbid).toBe("rec-1");
  });
});
