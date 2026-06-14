import { NextRequest, NextResponse } from "next/server";
import { searchTracks } from "@/app/lib/musicbrainz";

export interface SearchResult {
  type: "track";
  mbid: string;
  label: string;
  sub?: string;
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q")?.trim();
  if (!q) return NextResponse.json({ results: [] });

  const tracks = await searchTracks(q);
  const results: SearchResult[] = tracks.map((t) => ({
    type: "track",
    mbid: t.mbid,
    label: t.title,
    sub: t.artist,
  }));

  return NextResponse.json({ results });
}
