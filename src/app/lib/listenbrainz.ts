const LB_BASE = "https://api.listenbrainz.org/1";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

interface LBRecordingPopularity {
  recording_mbid: string;
  total_listen_count: number;
  total_user_count: number;
}

interface LBArtistPopularity {
  artist_mbid: string;
  total_listen_count: number;
  total_user_count: number;
}

export async function fetchRecordingPopularity(
  mbids: string[],
): Promise<Map<string, number>> {
  const validMbids = mbids.filter(Boolean);
  if (validMbids.length === 0) return new Map();
  try {
    const res = await fetch(`${LB_BASE}/popularity/recording/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({ recording_mbids: validMbids }),
    });
    if (!res.ok) return new Map();
    const data = (await res.json()) as LBRecordingPopularity[];
    return new Map(data.map((r) => [r.recording_mbid, r.total_listen_count]));
  } catch {
    return new Map();
  }
}

export async function fetchArtistPopularity(
  artistMbids: string[],
): Promise<Map<string, number>> {
  const validMbids = artistMbids.filter(Boolean);
  if (validMbids.length === 0) return new Map();
  try {
    const res = await fetch(`${LB_BASE}/popularity/artist/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({ artist_mbids: validMbids }),
    });
    if (!res.ok) return new Map();
    const data = (await res.json()) as LBArtistPopularity[];
    return new Map(data.map((r) => [r.artist_mbid, r.total_listen_count]));
  } catch {
    return new Map();
  }
}
