const LB_BASE = "https://api.listenbrainz.org/1";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

interface LBTagEntry {
  tag: string;
  count: number;
  genre_mbid?: string;
}

interface LBMetadataResponse {
  tag?: {
    recording?: LBTagEntry[];
    artist?: LBTagEntry[];
    release_group?: LBTagEntry[];
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
    const tagBlock = data[mbid]?.tag;
    if (!tagBlock) return [];
    const entries = [
      ...(tagBlock.recording ?? []),
      ...(tagBlock.artist ?? []),
      ...(tagBlock.release_group ?? []),
    ];
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

interface LBTopRecording {
  recording_mbid: string;
  recording_name: string;
  artist_mbids: string[];
  length: number | null;
  total_listen_count: number;
  total_user_count: number;
  tags?: LBTagEntry[];
}

export interface LBRecording {
  mbid: string;
  title: string;
  artistMbid: string;
  durationMs: number | null;
  listenCount: number;
  userCount: number;
  tags: string[];
}

export async function fetchArtistTopRecordings(
  artistMbid: string,
  limit: number,
): Promise<LBRecording[]> {
  try {
    const res = await fetch(
      `${LB_BASE}/popularity/top-recordings-for-artist/${encodeURIComponent(artistMbid)}`,
      { headers: { "User-Agent": USER_AGENT } },
    );
    if (!res.ok) {
      console.warn(
        `[lb] fetchArtistTopRecordings HTTP ${res.status} for ${artistMbid}`,
      );
      return [];
    }
    const data = (await res.json()) as LBTopRecording[];
    return data
      .filter((r) => {
        return r.recording_mbid && r.recording_name && r.artist_mbids?.[0];
      })
      .slice(0, limit)
      .map((r) => ({
        mbid: r.recording_mbid,
        title: r.recording_name,
        artistMbid: r.artist_mbids?.[0] ?? artistMbid,
        durationMs: r.length ?? null,
        listenCount: r.total_listen_count,
        userCount: r.total_user_count,
        tags: (r.tags ?? []).map((t) => t.tag.toLowerCase()),
      }));
  } catch (e) {
    console.error("[lb] fetchArtistTopRecordings failed:", e);
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
    const res = await fetch(`${LB_BASE}/popularity/recording`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({ recording_mbids: validMbids }),
    });
    if (!res.ok) {
      console.warn(
        `[lb] fetchRecordingPopularity HTTP ${res.status}: ${await res.text().catch(() => "")}`,
      );
      return new Map();
    }
    const data = (await res.json()) as LBRecordingPopularity[];
    const withData = data.filter((r) => r.total_listen_count !== null);
    console.log(
      `[lb] fetchRecordingPopularity: ${withData.length}/${validMbids.length} mbids returned data`,
    );
    return new Map(
      withData.map((r) => [r.recording_mbid, r.total_listen_count]),
    );
  } catch (e) {
    console.error("[lb] fetchRecordingPopularity failed:", e);
    return new Map();
  }
}

export async function fetchArtistPopularity(
  artistMbids: string[],
): Promise<Map<string, number>> {
  const validMbids = artistMbids.filter(Boolean);
  if (validMbids.length === 0) return new Map();
  try {
    const res = await fetch(`${LB_BASE}/popularity/artist`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({ artist_mbids: validMbids }),
    });
    if (!res.ok) {
      console.warn(
        `[lb] fetchArtistPopularity HTTP ${res.status}: ${await res.text().catch(() => "")}`,
      );
      return new Map();
    }
    const data = (await res.json()) as LBArtistPopularity[];
    const withData = data.filter((r) => r.total_listen_count !== null);
    console.log(
      `[lb] fetchArtistPopularity: ${withData.length}/${validMbids.length} mbids returned data`,
    );
    return new Map(withData.map((r) => [r.artist_mbid, r.total_listen_count]));
  } catch (e) {
    console.error("[lb] fetchArtistPopularity failed:", e);
    return new Map();
  }
}

