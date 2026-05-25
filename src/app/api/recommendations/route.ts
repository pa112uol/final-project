import { NextRequest, NextResponse } from "next/server";
import { mbFetch } from "../../lib/mb";

const MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2";
const ITUNES_BASE = "https://itunes.apple.com/search";
const YOUTUBE_SEARCH_BASE = "https://www.googleapis.com/youtube/v3/search";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";
const RECOMMENDATION_LIMIT = 10;

interface MBArtistCredit {
  artist: { id: string; name: string };
  name: string;
}

interface MBRelease {
  id: string;
  title: string;
  date?: string;
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

async function searchByArtists(artistNames: string[]): Promise<MBRecording[]> {
  const query = artistNames.map((a) => `artist:"${a}"`).join(" OR ");
  const url = new URL(`${MUSICBRAINZ_BASE}/recording`);
  url.searchParams.set("query", query);
  url.searchParams.set("limit", "50");
  url.searchParams.set("inc", "artist-credits releases");
  url.searchParams.set("fmt", "json");
  const res = await mbFetch(url.toString());
  if (!res.ok) return [];
  const data: { recordings?: MBRecording[] } = await res.json();
  return data.recordings ?? [];
}

function toTrackBase(r: MBRecording): Omit<Track, "streaming"> {
  const credit = r["artist-credit"]?.[0];
  return {
    mbid: r.id,
    title: r.title,
    artist: credit?.name ?? credit?.artist.name ?? "Unknown",
    artistMbid: credit?.artist.id ?? "",
    durationMs: r.length ?? null,
    firstReleaseDate: r["first-release-date"] ?? null,
    releases: (r.releases ?? []).map((rel) => ({
      mbid: rel.id,
      title: rel.title,
      date: rel.date,
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
    const res = await fetch(url.toString(), { headers: { "User-Agent": USER_AGENT } });
    if (res.ok) {
      const data: { results?: { trackViewUrl?: string; previewUrl?: string }[] } =
        await res.json();
      const result = data.results?.[0];
      return {
        appleMusic: result?.trackViewUrl ?? null,
        preview: result?.previewUrl ?? null,
      };
    }
  } catch {}
  return { appleMusic: null, preview: null };
}

async function getYoutubeVideoId(artist: string, title: string): Promise<string | null> {
  const apiKey = process.env.YOUTUBE_API_KEY;
  if (!apiKey) return null;
  try {
    const url = new URL(YOUTUBE_SEARCH_BASE);
    url.searchParams.set("part", "snippet");
    url.searchParams.set("q", `"${artist}" "${title}"`);
    url.searchParams.set("type", "video");
    url.searchParams.set("videoCategoryId", "10");
    url.searchParams.set("maxResults", "1");
    url.searchParams.set("key", apiKey);
    const res = await fetch(url.toString());
    if (res.ok) {
      const data: { items?: { id?: { videoId?: string } }[] } = await res.json();
      return data.items?.[0]?.id?.videoId ?? null;
    }
  } catch {}
  return null;
}

async function getStreamingLinks(artist: string, title: string): Promise<StreamingLinks> {
  const query = encodeURIComponent(`${artist} ${title}`);
  const [itunes, youtubeVideoId] = await Promise.all([
    getItunesLinks(artist, title),
    getYoutubeVideoId(artist, title),
  ]);
  return {
    appleMusic: itunes.appleMusic,
    preview: itunes.preview,
    youtubeVideoId,
    spotify: `https://open.spotify.com/search/${query}`,
  };
}

export async function GET(req: NextRequest) {
  const titles = req.nextUrl.searchParams.getAll("title");
  const artists = req.nextUrl.searchParams.getAll("artist");

  if (titles.length === 0) {
    return NextResponse.json({ error: "No seed tracks provided" }, { status: 400 });
  }

  const seeds = titles.map((t, i) => ({
    title: t.toLowerCase(),
    artist: (artists[i] ?? "").toLowerCase(),
  }));

  // Deduplicate artist names and search MB for recordings by those artists
  const uniqueArtists = [...new Set(seeds.map((s) => s.artist).filter(Boolean))];
  const candidates = await searchByArtists(uniqueArtists);

  // Exclude exact seed tracks by title+artist match
  const seedKeys = new Set(seeds.map((s) => `${s.title}|||${s.artist}`));
  const filtered = candidates.filter((r) => {
    const credit = r["artist-credit"]?.[0];
    const artistName = (credit?.name ?? credit?.artist.name ?? "").toLowerCase();
    const key = `${r.title.toLowerCase()}|||${artistName}`;
    return !seedKeys.has(key);
  });

  const top = filtered.slice(0, RECOMMENDATION_LIMIT);

  const tracks = await Promise.all(
    top.map(async (recording) => {
      const base = toTrackBase(recording);
      return { ...base, streaming: await getStreamingLinks(base.artist, base.title) };
    }),
  );

  return NextResponse.json({ tracks });
}
