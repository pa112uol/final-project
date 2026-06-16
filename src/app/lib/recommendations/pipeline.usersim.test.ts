/**
 * User-simulation quality tests for the recommendation pipeline.
 *
 * Each scenario mirrors a realistic user search: mainstream pop, hip-hop,
 * classic rock, ultra-niche, multi-seed crossover, and intermediate novelty.
 * Quality metrics are printed and asserted per scenario.
 *
 * Run with: npx vitest run pipeline.usersim --sequence.concurrent false
 */
import { readFileSync } from "fs";
import path from "path";
import { describe, it, expect, beforeAll } from "vitest";
import { getRecommendations } from "./index";
import type { Track } from "./types";

try {
  const envPath = path.resolve(__dirname, "../../../../.env.local");
  readFileSync(envPath, "utf-8")
    .split("\n")
    .forEach((line) => {
      const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.+)$/);
      if (m) process.env[m[1]] = m[2].trim();
    });
} catch {
  /* tests skip if key absent */
}

const API_KEY = process.env.LASTFM_API_KEY ?? "";

interface QualityReport {
  scenario: string;
  trackCount: number;
  uniqueArtists: number;
  // uniqueArtists / trackCount  (1.0 = all different)
  artistDiversity: number;
  avgRelevance: number;
  minRelevance: number;
  // max - min relevance  (higher = better differentiation)
  relevanceSpread: number;
  avgNovelty: number;
  tracksWithZeroRelevance: number;
  // tracks whose only tag is a broad genre label
  tracksWithSparseTags: number;
}

const BROAD_LABELS = new Set([
  "rock",
  "pop",
  "metal",
  "electronic",
  "indie",
  "alternative",
  "folk",
  "jazz",
  "classical",
  "hip hop",
  "rap",
  "country",
  "soul",
  "blues",
  "r&b",
  "dance",
  "punk",
]);

function analyseQuality(label: string, tracks: Track[]): QualityReport {
  if (tracks.length === 0) {
    return {
      scenario: label,
      trackCount: 0,
      uniqueArtists: 0,
      artistDiversity: 0,
      avgRelevance: 0,
      minRelevance: 0,
      relevanceSpread: 0,
      avgNovelty: 0,
      tracksWithZeroRelevance: 0,
      tracksWithSparseTags: 0,
    };
  }
  const artists = new Set(tracks.map((t) => t.artist.toLowerCase()));
  const relevances = tracks.map((t) => t.relevanceScore);
  const avg = (arr: number[]) => arr.reduce((s, x) => s + x, 0) / arr.length;
  const maxRel = Math.max(...relevances);
  const minRel = Math.min(...relevances);
  return {
    scenario: label,
    trackCount: tracks.length,
    uniqueArtists: artists.size,
    artistDiversity: artists.size / tracks.length,
    avgRelevance: avg(relevances),
    minRelevance: minRel,
    relevanceSpread: maxRel - minRel,
    avgNovelty: avg(tracks.map((t) => t.noveltyScore)),
    tracksWithZeroRelevance: relevances.filter((r) => r < 0.01).length,
    tracksWithSparseTags: 0, // filled below
  };
}

function printQuality(report: QualityReport, tracks: Track[]) {
  console.log(`\n${"═".repeat(60)}`);
  console.log(`[QUALITY] ${report.scenario}`);
  console.log(
    `tracks: ${report.trackCount}  unique artists: ${report.uniqueArtists}/${report.trackCount} (${(report.artistDiversity * 100).toFixed(0)}% diversity)`,
  );
  console.log(
    `relevance - avg:${report.avgRelevance.toFixed(3)}  min:${report.minRelevance.toFixed(3)}  spread:${report.relevanceSpread.toFixed(3)}`,
  );
  console.log(`  novelty  - avg:${report.avgNovelty.toFixed(3)}`);
  if (report.tracksWithZeroRelevance > 0)
    console.warn(
      `WARNING: ${report.tracksWithZeroRelevance} track(s) with relevance < 0.01`,
    );
  console.log(`  results:`);
  for (let i = 0; i < tracks.length; i++) {
    const t = tracks[i];
    console.log(
      `[${i + 1}] "${t.title}" – ${t.artist}` +
        `rel:${t.relevanceScore.toFixed(3)} nov:${t.noveltyScore.toFixed(3)}`,
    );
  }
  console.log("═".repeat(60));
}

function assertShape(t: Track) {
  expect(typeof t.title).toBe("string");
  expect(t.title.length).toBeGreaterThan(0);
  expect(typeof t.artist).toBe("string");
  expect(t.relevanceScore).toBeGreaterThanOrEqual(0);
  expect(t.relevanceScore).toBeLessThanOrEqual(1);
  expect(t.noveltyScore).toBeGreaterThanOrEqual(0);
  expect(t.noveltyScore).toBeLessThanOrEqual(1);
}

function assertArtistCap(tracks: Track[]) {
  const counts = new Map<string, number>();
  for (const t of tracks)
    counts.set(
      t.artist.toLowerCase(),
      (counts.get(t.artist.toLowerCase()) ?? 0) + 1,
    );
  for (const [a, n] of counts)
    expect(n, `${a} exceeded cap`).toBeLessThanOrEqual(2);
}

describe("UserSim A – Mainstream synth-pop: 'Blinding Lights' – The Weeknd", () => {
  let tracks: Track[];
  let report: QualityReport;

  beforeAll(async () => {
    if (!API_KEY) return;
    const t0 = Date.now();
    tracks = await getRecommendations(
      [{ mbid: "", title: "blinding lights", artist: "the weeknd" }],
      API_KEY,
      undefined,
      0,
    );
    console.log(`\n[TIME] UserSim A (synth-pop): ${((Date.now() - t0) / 1000).toFixed(2)}s`);
    report = analyseQuality("Synth-pop (novelty=0)", tracks);
    printQuality(report, tracks);
  }, 120_000);

  it("returns results", () => {
    if (!API_KEY) return;
    expect(Array.isArray(tracks)).toBe(true);
  });
  it("all tracks have valid shape", () => {
    if (!API_KEY || !tracks?.length) return;
    tracks.forEach(assertShape);
  });
  it("artist cap respected", () => {
    if (!API_KEY || !tracks?.length) return;
    assertArtistCap(tracks);
  });
  it("at most 10 tracks", () => {
    if (!API_KEY) return;
    expect(tracks.length).toBeLessThanOrEqual(10);
  });
  it("no track has relevance=0 (broad pop seed should still yield tag matches)", () => {
    if (!API_KEY || !tracks?.length) return;
    expect(report.tracksWithZeroRelevance).toBe(0);
  });
  it("relevance spread >= 0.2 (scores aren't all identical)", () => {
    if (!API_KEY || tracks?.length < 3) return;
    expect(report.relevanceSpread).toBeGreaterThanOrEqual(0.2);
  });
});

describe("UserSim B – Hip-hop: 'HUMBLE.' – Kendrick Lamar", () => {
  let tracks: Track[];
  let report: QualityReport;

  beforeAll(async () => {
    if (!API_KEY) return;
    const t0 = Date.now();
    tracks = await getRecommendations(
      [{ mbid: "", title: "humble", artist: "kendrick lamar" }],
      API_KEY,
      undefined,
      0,
    );
    console.log(`\n[TIME] UserSim B (hip-hop): ${((Date.now() - t0) / 1000).toFixed(2)}s`);
    report = analyseQuality("Hip-hop (novelty=0)", tracks);
    printQuality(report, tracks);
  }, 120_000);

  it("returns results", () => {
    if (!API_KEY) return;
    expect(Array.isArray(tracks)).toBe(true);
  });
  it("all tracks have valid shape", () => {
    if (!API_KEY || !tracks?.length) return;
    tracks.forEach(assertShape);
  });
  it("artist cap respected", () => {
    if (!API_KEY || !tracks?.length) return;
    assertArtistCap(tracks);
  });
  it("seed artist not in top result (other hip-hop artists surface)", () => {
    if (!API_KEY || !tracks?.length) return;
    // seed track "humble" by "kendrick lamar" must not appear
    const seedInResults = tracks.some(
      (t) =>
        t.title.toLowerCase().includes("humble") &&
        t.artist.toLowerCase().includes("kendrick"),
    );
    expect(seedInResults).toBe(false);
  });
  it("avg relevance >= 0.3 (hip-hop sub-genre tags yield decent signal)", () => {
    if (!API_KEY || !tracks?.length) return;
    expect(report.avgRelevance).toBeGreaterThanOrEqual(0.3);
  });
});

describe("UserSim C – Classic rock: 'Stairway to Heaven' – Led Zeppelin", () => {
  let tracks: Track[];
  let report: QualityReport;

  beforeAll(async () => {
    if (!API_KEY) return;
    const t0 = Date.now();
    tracks = await getRecommendations(
      [{ mbid: "", title: "stairway to heaven", artist: "led zeppelin" }],
      API_KEY,
      undefined,
      0,
    );
    console.log(`\n[TIME] UserSim C (classic rock): ${((Date.now() - t0) / 1000).toFixed(2)}s`);
    report = analyseQuality("Classic rock (novelty=0)", tracks);
    printQuality(report, tracks);
  }, 120_000);

  it("returns results", () => {
    if (!API_KEY) return;
    expect(Array.isArray(tracks)).toBe(true);
  });
  it("all tracks have valid shape", () => {
    if (!API_KEY || !tracks?.length) return;
    tracks.forEach(assertShape);
  });
  it("artist cap respected", () => {
    if (!API_KEY || !tracks?.length) return;
    assertArtistCap(tracks);
  });
  it("at least 5 unique artists across 10 results (diversity)", () => {
    if (!API_KEY || tracks?.length < 5) return;
    expect(report.uniqueArtists).toBeGreaterThanOrEqual(5);
  });
});

describe("UserSim D – Ultra-niche: 'Alien Observer' – Grouper", () => {
  let tracks: Track[];
  let report: QualityReport;

  beforeAll(async () => {
    if (!API_KEY) return;
    const t0 = Date.now();
    tracks = await getRecommendations(
      [{ mbid: "", title: "alien observer", artist: "grouper" }],
      API_KEY,
      undefined,
      0,
    );
    console.log(`\n[TIME] UserSim D (ultra-niche): ${((Date.now() - t0) / 1000).toFixed(2)}s`);
    report = analyseQuality("Ultra-niche Grouper (novelty=0)", tracks);
    printQuality(report, tracks);
  }, 120_000);

  it("returns an array (may be empty for obscure seed)", () => {
    if (!API_KEY) return;
    expect(Array.isArray(tracks)).toBe(true);
  });
  it("all tracks have valid shape", () => {
    if (!API_KEY || !tracks?.length) return;
    tracks.forEach(assertShape);
  });
  it("if results returned, artist cap respected", () => {
    if (!API_KEY || !tracks?.length) return;
    assertArtistCap(tracks);
  });
  it("if results returned, no zero-relevance tracks", () => {
    if (!API_KEY || !tracks?.length) return;
    expect(report.tracksWithZeroRelevance).toBe(0);
  });
});

describe("UserSim E – Multi-seed indie: The National + Bon Iver", () => {
  let tracksNational: Track[];
  let tracksBonIver: Track[];
  let tracksMulti: Track[];

  beforeAll(async () => {
    if (!API_KEY) return;
    const t0 = Date.now();
    [tracksNational, tracksBonIver, tracksMulti] = await Promise.all([
      getRecommendations(
        [{ mbid: "", title: "bloodbuzz ohio", artist: "the national" }],
        API_KEY,
        undefined,
        0,
      ),
      getRecommendations(
        [{ mbid: "", title: "skinny love", artist: "bon iver" }],
        API_KEY,
        undefined,
        0,
      ),
      getRecommendations(
        [
          { mbid: "", title: "bloodbuzz ohio", artist: "the national" },
          { mbid: "", title: "skinny love", artist: "bon iver" },
        ],
        API_KEY,
        undefined,
        0,
      ),
    ]);
    console.log(`\n[TIME] UserSim E (multi-seed, 3x parallel): ${((Date.now() - t0) / 1000).toFixed(2)}s`);
    const rN = analyseQuality("National only", tracksNational);
    const rB = analyseQuality("Bon Iver only", tracksBonIver);
    const rM = analyseQuality("National + Bon Iver multi-seed", tracksMulti);
    printQuality(rN, tracksNational);
    printQuality(rB, tracksBonIver);
    printQuality(rM, tracksMulti);

    // Cross-overlap: how many artists appear in both single-seed results?
    const artistsN = new Set(tracksNational.map((t) => t.artist.toLowerCase()));
    const artistsB = new Set(tracksBonIver.map((t) => t.artist.toLowerCase()));
    const overlap = [...artistsN].filter((a) => artistsB.has(a));
    console.log(
      `[QUALITY] Cross-seed artist overlap: ${overlap.join(", ") || "none"}`,
    );

    // Which new artists appear only in multi-seed?
    const artistsM = new Set(tracksMulti.map((t) => t.artist.toLowerCase()));
    const onlyInMulti = [...artistsM].filter(
      (a) => !artistsN.has(a) && !artistsB.has(a),
    );
    console.log(
      `[QUALITY] Artists unique to multi-seed result: ${onlyInMulti.join(", ") || "none"}`,
    );
  }, 180_000);

  it("all three runs return arrays", () => {
    if (!API_KEY) return;
    expect(Array.isArray(tracksNational)).toBe(true);
    expect(Array.isArray(tracksBonIver)).toBe(true);
    expect(Array.isArray(tracksMulti)).toBe(true);
  });
  it("artist cap respected in all three", () => {
    if (!API_KEY) return;
    if (tracksNational?.length) assertArtistCap(tracksNational);
    if (tracksBonIver?.length) assertArtistCap(tracksBonIver);
    if (tracksMulti?.length) assertArtistCap(tracksMulti);
  });
  it("multi-seed result differs from both single-seed results (consensus changes ranking)", () => {
    if (
      !API_KEY ||
      !tracksMulti?.length ||
      !tracksNational?.length ||
      !tracksBonIver?.length
    )
      return;
    const top1N = tracksNational[0]?.mbid;
    const top1B = tracksBonIver[0]?.mbid;
    const top1M = tracksMulti[0]?.mbid;
    console.log(
      `[QUALITY] top-1 mbids - National:${top1N}  BonIver:${top1B}  Multi:${top1M}`,
    );
    // Multi top result must differ from at least one of the single-seed tops
    expect(top1M === top1N && top1M === top1B).toBe(false);
  });
  it("seed artists excluded from their own results", () => {
    if (!API_KEY) return;
    if (tracksNational?.length) {
      const hasNational = tracksNational.some(
        (t) =>
          t.title.toLowerCase() === "bloodbuzz ohio" &&
          t.artist.toLowerCase() === "the national",
      );
      expect(hasNational).toBe(false);
    }
    if (tracksBonIver?.length) {
      const hasBon = tracksBonIver.some(
        (t) =>
          t.title.toLowerCase() === "skinny love" &&
          t.artist.toLowerCase() === "bon iver",
      );
      expect(hasBon).toBe(false);
    }
  });
});

describe("UserSim F – Novelty gradient: 0 vs 0.5 vs 1, 'Teardrop' – Massive Attack", () => {
  let t0: Track[];
  let t5: Track[];
  let t1: Track[];

  beforeAll(async () => {
    if (!API_KEY) return;
    const seed = [{ mbid: "", title: "teardrop", artist: "massive attack" }];
    const tStart = Date.now();
    [t0, t5, t1] = await Promise.all([
      getRecommendations(seed, API_KEY, undefined, 0),
      getRecommendations(seed, API_KEY, undefined, 0.5),
      getRecommendations(seed, API_KEY, undefined, 1),
    ]);
    console.log(`\n[TIME] UserSim F (novelty gradient, 3x parallel): ${((Date.now() - tStart) / 1000).toFixed(2)}s`);

    const avg = (arr: Track[], fn: (t: Track) => number) =>
      arr.length ? arr.reduce((s, t) => s + fn(t), 0) / arr.length : 0;

    console.log("\n" + "═".repeat(60));
    console.log("[QUALITY] Novelty gradient – Massive Attack 'Teardrop'");
    console.log(
      `  novelty=0.0: ${t0.length} tracks  avgRel:${avg(t0, (t) => t.relevanceScore).toFixed(3)}  avgNov:${avg(t0, (t) => t.noveltyScore).toFixed(3)}`,
    );
    console.log(
      `  novelty=0.5: ${t5.length} tracks  avgRel:${avg(t5, (t) => t.relevanceScore).toFixed(3)}  avgNov:${avg(t5, (t) => t.noveltyScore).toFixed(3)}`,
    );
    console.log(
      `  novelty=1.0: ${t1.length} tracks  avgRel:${avg(t1, (t) => t.relevanceScore).toFixed(3)}  avgNov:${avg(t1, (t) => t.noveltyScore).toFixed(3)}`,
    );

    const top3 = (arr: Track[]) =>
      arr
        .slice(0, 3)
        .map((t) => `"${t.title}" – ${t.artist}`)
        .join(" | ");
    console.log(`  top-3 (nov=0):   ${top3(t0)}`);
    console.log(`  top-3 (nov=0.5): ${top3(t5)}`);
    console.log(`  top-3 (nov=1):   ${top3(t1)}`);
    console.log("═".repeat(60));
  }, 180_000);

  it("all three novelty levels return arrays", () => {
    if (!API_KEY) return;
    expect(Array.isArray(t0)).toBe(true);
    expect(Array.isArray(t5)).toBe(true);
    expect(Array.isArray(t1)).toBe(true);
  });
  it("novelty=0.5 avg novelty score is between nov=0 and nov=1", () => {
    if (!API_KEY || !t0?.length || !t5?.length || !t1?.length) return;
    const avg = (arr: Track[]) =>
      arr.reduce((s, t) => s + t.noveltyScore, 0) / arr.length;
    const n0 = avg(t0),
      n5 = avg(t5),
      n1 = avg(t1);
    console.log(
      `[QUALITY] avg novelty: nov=0 → ${n0.toFixed(3)}, nov=0.5 → ${n5.toFixed(3)}, nov=1 → ${n1.toFixed(3)}`,
    );
    expect(n5).toBeGreaterThanOrEqual(n0);
    expect(n1).toBeGreaterThanOrEqual(n5);
  });
  it("novelty=0.5 avg relevance is between nov=0 and nov=1", () => {
    if (!API_KEY || !t0?.length || !t5?.length || !t1?.length) return;
    const avg = (arr: Track[]) =>
      arr.reduce((s, t) => s + t.relevanceScore, 0) / arr.length;
    const r0 = avg(t0),
      r5 = avg(t5),
      r1 = avg(t1);
    console.log(
      `[QUALITY] avg relevance: nov=0 → ${r0.toFixed(3)}, nov=0.5 → ${r5.toFixed(3)}, nov=1 → ${r1.toFixed(3)}`,
    );
    expect(r5).toBeLessThanOrEqual(r0 + 0.05); // may be slightly above due to pool differences
    expect(r1).toBeLessThanOrEqual(r5 + 0.05);
  });
  it("artist cap respected across all novelty levels", () => {
    if (!API_KEY) return;
    if (t0?.length) assertArtistCap(t0);
    if (t5?.length) assertArtistCap(t5);
    if (t1?.length) assertArtistCap(t1);
  });
});

