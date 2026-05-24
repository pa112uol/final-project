import { NextRequest, NextResponse } from "next/server";

const LASTFM_BASE = "https://ws.audioscrobbler.com/2.0";

export interface SearchResult {
  type: "track";
  mbid: string;
  label: string;
  sub?: string;
}

interface LastFmTrack {
  name: string;
  artist: string;
  mbid: string;
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q")?.trim();
  if (!q) return NextResponse.json({ results: [] });

  const apiKey = process.env.LASTFM_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "LASTFM_API_KEY not set" }, { status: 500 });
  }

  const url = new URL(LASTFM_BASE);
  url.searchParams.set("method", "track.search");
  url.searchParams.set("track", q);
  url.searchParams.set("limit", "15");
  url.searchParams.set("api_key", apiKey);
  url.searchParams.set("format", "json");

  try {
    const res = await fetch(url.toString());
    if (!res.ok) return NextResponse.json({ results: [] });

    const data = await res.json();
    const tracks: LastFmTrack[] =
      data.results?.trackmatches?.track ?? [];

    // Filter out results with no mbid, then deduplicate by title+artist
    const seen = new Set<string>();
    const results: SearchResult[] = [];

    for (const t of tracks) {
      if (!t.mbid) continue;
      const key = `${t.name.toLowerCase()}|${t.artist.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      results.push({
        type: "track",
        mbid: t.mbid,
        label: t.name,
        sub: t.artist,
      });
      if (results.length === 10) break;
    }

    return NextResponse.json({ results });
  } catch {
    return NextResponse.json({ results: [] });
  }
}
