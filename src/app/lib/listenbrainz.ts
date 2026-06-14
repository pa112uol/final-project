const LB_BASE = "https://api.listenbrainz.org/1";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

interface LBTagEntry {
  tag: string;
  count: number;
  genre_mbid?: string;
}

interface LBMetadataResponse {
  metadata?: {
    tag?: {
      recording?: LBTagEntry[];
      artist?: LBTagEntry[];
      release_group?: LBTagEntry[];
    };
  };
}

export async function fetchRecordingTags(
  mbid: string,
): Promise<{ name: string; count: number }[]> {
  if (!mbid) return [];
  try {
    const res = await fetch(
      `${LB_BASE}/metadata/recording/?recording_mbids=${encodeURIComponent(mbid)}&inc=tag`,
      { headers: { "User-Agent": USER_AGENT } },
    );
    if (!res.ok) return [];
    const data = (await res.json()) as Record<string, LBMetadataResponse>;
    const tagBlock = data[mbid]?.metadata?.tag;
    if (!tagBlock) return [];
    const entries = [...(tagBlock.recording ?? []), ...(tagBlock.artist ?? [])];
    const merged = new Map<string, number>();
    for (const { tag, count } of entries) {
      const name = tag.toLowerCase().trim();
      if (name) merged.set(name, (merged.get(name) ?? 0) + count);
    }
    return [...merged.entries()].map(([name, count]) => ({ name, count }));
  } catch {
    return [];
  }
}

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

