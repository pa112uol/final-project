import { NextRequest, NextResponse } from "next/server";
import { getRecommendations, MOOD_TAGS, Seed } from "@/app/lib/recommendations";

function makeLogger(reqId: string, startMs: number) {
  return (phase: string, data: unknown) =>
    console.log(`[REC:${phase} ${reqId} +${Date.now() - startMs}ms]`, JSON.stringify(data));
}

export async function GET(req: NextRequest) {
  const startMs = Date.now();
  const log = makeLogger(Math.random().toString(36).slice(2, 7), startMs);

  const apiKey = process.env.LASTFM_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "LASTFM_API_KEY not set" }, { status: 500 });
  }

  const sp = req.nextUrl.searchParams;
  const mbids = sp.getAll("mbid");
  const titles = sp.getAll("title");
  const artists = sp.getAll("artist");
  const mood = sp.get("mood")?.toLowerCase().trim() || undefined;
  const noveltyRaw = parseFloat(sp.get("novelty") ?? "0");
  const novelty = Number.isNaN(noveltyRaw) ? 0 : Math.max(0, Math.min(1, noveltyRaw));

  if (mbids.length === 0) {
    return NextResponse.json({ error: "No seed tracks provided" }, { status: 400 });
  }
  if (mood && !MOOD_TAGS[mood]) {
    return NextResponse.json(
      { error: `Unknown mood. Valid values: ${Object.keys(MOOD_TAGS).join(", ")}` },
      { status: 400 },
    );
  }

  const seeds: Seed[] = mbids.map((mbid, i) => ({
    mbid,
    title: (titles[i] ?? "").toLowerCase().trim(),
    artist: (artists[i] ?? "").toLowerCase().trim(),
  }));

  log("input", { seeds, mood: mood ?? null, novelty });

  const tracks = await getRecommendations(seeds, apiKey, mood, novelty);

  log("result", { tracksReturned: tracks.length, totalMs: Date.now() - startMs });

  return NextResponse.json({ tracks });
}
