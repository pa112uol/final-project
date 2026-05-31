const LASTFM_BASE = "https://ws.audioscrobbler.com/2.0";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

export interface LFTag {
  name: string;
  count: number;
}

export interface LFTrack {
  name: string;
  duration?: string;
  mbid?: string;
  artist: { name: string; mbid?: string };
}

async function lfFetch<T>(params: Record<string, string>, apiKey: string): Promise<T | null> {
  const url = new URL(LASTFM_BASE);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  url.searchParams.set("api_key", apiKey);
  url.searchParams.set("format", "json");
  try {
    const res = await fetch(url.toString(), { headers: { "User-Agent": USER_AGENT } });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function parseTags(raw: unknown): LFTag[] {
  if (!raw) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  return (arr as { name?: string; count?: unknown }[])
    .map((t) => ({ name: (t.name ?? "").toLowerCase().trim(), count: Number(t.count) }))
    .filter((t) => t.name.length > 0);
}

export async function fetchSeedTags(
  title: string,
  artist: string,
  apiKey: string,
  mbid?: string,
): Promise<LFTag[]> {
  const params: Record<string, string> = {
    method: "track.getTopTags",
    track: title,
    artist,
    autocorrect: "1",
  };
  if (mbid) params.mbid = mbid;

  const trackData = await lfFetch<{ toptags?: { tag?: unknown } }>(params, apiKey);
  const trackTags = parseTags(trackData?.toptags?.tag);
  if (trackTags.length > 0) return trackTags;

  const artistData = await lfFetch<{ toptags?: { tag?: unknown } }>(
    { method: "artist.getTopTags", artist, autocorrect: "1" },
    apiKey,
  );
  return parseTags(artistData?.toptags?.tag);
}


export interface LFArtist {
  name: string;
  mbid?: string;
}

export async function fetchTagArtists(
  tag: string,
  page: number,
  limit: number,
  apiKey: string,
): Promise<LFArtist[]> {
  const data = await lfFetch<{ topartists?: { artist?: unknown } }>(
    { method: "tag.getTopArtists", tag, limit: String(limit), page: String(page) },
    apiKey,
  );
  const raw = data?.topartists?.artist;
  if (!raw) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  return (arr as { name?: string; mbid?: string }[])
    .map((a) => ({ name: a.name ?? "", mbid: a.mbid }))
    .filter((a) => a.name.length > 0);
}

export async function fetchArtistTopTracks(
  artist: string,
  limit: number,
  apiKey: string,
): Promise<LFTrack[]> {
  const data = await lfFetch<{ toptracks?: { track?: unknown } }>(
    { method: "artist.getTopTracks", artist, limit: String(limit), autocorrect: "1" },
    apiKey,
  );
  const raw = data?.toptracks?.track;
  if (!raw) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  return arr as LFTrack[];
}
