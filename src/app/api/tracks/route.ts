import { NextResponse } from "next/server";

const MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2";
const ITUNES_BASE = "https://itunes.apple.com/search";
const YOUTUBE_SEARCH_BASE = "https://www.googleapis.com/youtube/v3/search";
const USER_AGENT = "3070-final-project/1.0 (contact@example.com)";
const RESPONSE_LIMIT = 5;
const CACHE_TTL_MS = 60_000;

interface MBRelease {
  id: string;
  title: string;
  date?: string;
}

interface MBArtistCredit {
  artist: { id: string; name: string };
  name: string;
}

interface MBRecording {
  id: string;
  title: string;
  length?: number;
  "artist-credit"?: MBArtistCredit[];
  releases?: MBRelease[];
  "first-release-date"?: string;
}

interface StreamingLinks {
  appleMusic: string | null;
  preview: string | null;
  youtubeVideoId: string | null;
  spotify: string;
}

interface Track {
  mbid: string;
  title: string;
  artist: string;
  artistMbid: string;
  durationMs: number | null;
  firstReleaseDate: string | null;
  releases: { mbid: string; title: string; date?: string }[];
  streaming: StreamingLinks;
}

interface Cache {
  pool: Omit<Track, "streaming">[];
  expiresAt: number;
}

let cache: Cache | null = null;

function randomLetter(): string {
  return String.fromCharCode(97 + Math.floor(Math.random() * 26));
}

function toBaseTrack(recording: MBRecording): Omit<Track, "streaming"> {
  const credit = recording["artist-credit"]?.[0];
  return {
    mbid: recording.id,
    title: recording.title,
    artist: credit?.name ?? credit?.artist.name ?? "Unknown",
    artistMbid: credit?.artist.id ?? "",
    durationMs: recording.length ?? null,
    firstReleaseDate: recording["first-release-date"] ?? null,
    releases: (recording.releases ?? []).map((r) => ({
      mbid: r.id,
      title: r.title,
      date: r.date,
    })),
  };
}

async function getItunesLinks(
  artist: string,
  title: string,
): Promise<{ appleMusic: string | null; preview: string | null }> {
  try {
    const url = new URL(ITUNES_BASE);
    url.searchParams.set("term", `${artist} ${title}`);
    url.searchParams.set("entity", "song");
    url.searchParams.set("limit", "1");

    const res = await fetch(url.toString(), {
      headers: { "User-Agent": USER_AGENT },
    });

    if (res.ok) {
      const data = await res.json();
      const result = data.results?.[0];
      return {
        appleMusic: result?.trackViewUrl ?? null,
        preview: result?.previewUrl ?? null,
      };
    }
  } catch {}

  return { appleMusic: null, preview: null };
}

async function getYoutubeVideoId(
  artist: string,
  title: string,
): Promise<string | null> {
  const apiKey = process.env.YOUTUBE_API_KEY;
  if (!apiKey) return null;

  try {
    const url = new URL(YOUTUBE_SEARCH_BASE);
    url.searchParams.set("part", "snippet");
    // Search for an exact match of "artist title" to increase chances of getting the correct video
    url.searchParams.set("q", `"${artist}" "${title}"`);
    url.searchParams.set("type", "video");
    // Filter by music category to improve relevance
    url.searchParams.set("videoCategoryId", "10");
    url.searchParams.set("maxResults", "1");
    url.searchParams.set("key", apiKey);

    const res = await fetch(url.toString());
    if (res.ok) {
      const data = await res.json();
      return data.items?.[0]?.id?.videoId ?? null;
    }
  } catch {}

  return null;
}

async function getStreamingLinks(
  artist: string,
  title: string,
): Promise<StreamingLinks> {
  const query = encodeURIComponent(`${artist} ${title}`);
  const spotify = `https://open.spotify.com/search/${query}`;

  const [itunes, youtubeVideoId] = await Promise.all([
    getItunesLinks(artist, title),
    getYoutubeVideoId(artist, title),
  ]);

  return {
    appleMusic: itunes.appleMusic,
    preview: itunes.preview,
    youtubeVideoId,
    spotify,
  };
}

async function fetchPage(
  letter: string,
  offset: number,
): Promise<MBRecording[]> {
  const url = new URL(`${MUSICBRAINZ_BASE}/recording`);
  url.searchParams.set("query", `recording:${letter}*`);
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", "25");
  url.searchParams.set("inc", "artist-credits releases");
  url.searchParams.set("fmt", "json");

  const response = await fetch(url.toString(), {
    headers: { "User-Agent": USER_AGENT },
    next: { revalidate: 0 },
  });

  if (!response.ok)
    throw new Error(`MusicBrainz responded with ${response.status}`);
  const data = await response.json();
  return data.recordings as MBRecording[];
}

async function buildPool(): Promise<Omit<Track, "streaming">[]> {
  const letter = randomLetter();
  const offset = Math.floor(Math.random() * 400);
  const recordings = await fetchPage(letter, offset);
  return recordings.map(toBaseTrack);
}

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export async function GET() {
  if (!cache || Date.now() > cache.expiresAt) {
    try {
      const pool = await buildPool();
      cache = { pool, expiresAt: Date.now() + CACHE_TTL_MS };
    } catch {
      return NextResponse.json(
        { error: "Failed to fetch tracks from MusicBrainz" },
        { status: 502 },
      );
    }
  }

  const selected = shuffle(cache.pool).slice(0, RESPONSE_LIMIT);
  const tracks = await Promise.all(
    selected.map(async (track) => ({
      ...track,
      streaming: await getStreamingLinks(track.artist, track.title),
    })),
  );

  return NextResponse.json({ tracks });
}

