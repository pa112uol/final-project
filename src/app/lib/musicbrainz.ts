const MB_BASE = "https://musicbrainz.org/ws/2";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

interface MBRecording {
  id: string;
  title: string;
  score: number;
  "artist-credit"?: { name: string; artist: { name: string } }[];
}

export interface MBTrackResult {
  mbid: string;
  title: string;
  artist: string;
}

function buildMbQuery(q: string): string {
  const escape = (s: string) => s.replace(/[+\-&|!(){}[\]^"~*?:\\/]/g, "\\$&");

  // "artist - track" => split into dedicated fields for precision
  const dashMatch = q.match(/^(.+?)\s+-\s+(.+)$/);
  if (dashMatch) {
    return `recording:(${escape(dashMatch[2].trim())})^2 AND artist:(${escape(dashMatch[1].trim())})`;
  }

  // Free-text: search both fields with all words, boost title matches
  const escaped = escape(q);
  return `recording:(${escaped})^2 AND artist:(${escaped})`;
}

export async function searchTracks(q: string): Promise<MBTrackResult[]> {
  const query = buildMbQuery(q);

  const url = new URL(`${MB_BASE}/recording`);
  url.searchParams.set("query", query);
  url.searchParams.set("limit", "15");
  url.searchParams.set("fmt", "json");

  try {
    const res = await fetch(url.toString(), {
      headers: { "User-Agent": USER_AGENT },
    });
    if (!res.ok) return [];
    const data = await res.json();
    const recordings: MBRecording[] = data.recordings ?? [];

    const seen = new Set<string>();
    const results: MBTrackResult[] = [];

    for (const r of recordings) {
      if (!r.id) continue;
      const artist = r["artist-credit"]?.[0]?.name ?? "";
      const key = `${r.title.toLowerCase()}|${artist.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      results.push({ mbid: r.id, title: r.title, artist });
      if (results.length === 10) break;
    }

    return results;
  } catch {
    return [];
  }
}

export async function resolveCanonicalMbid(mbid: string): Promise<string> {
  try {
    const res = await fetch(`${MB_BASE}/recording/${mbid}?fmt=json`, {
      headers: { "User-Agent": USER_AGENT },
    });
    if (!res.ok) return mbid;
    const data = (await res.json()) as { id?: string };
    return data.id ?? mbid;
  } catch {
    return mbid;
  }
}

