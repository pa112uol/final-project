const ITUNES_BASE = "https://itunes.apple.com/search";
const YOUTUBE_SEARCH_BASE = "https://www.googleapis.com/youtube/v3/search";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";

export interface StreamingLinks {
  appleMusic: string | null;
  preview: string | null;
  youtubeVideoId: string | null;
  spotify: string;
}

function forceHttps(url?: string | null): string | null {
  if (!url) return null;
  return url.replace(/^http:\/\//, "https://");
}

async function fetchItunesLinks(
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
      cache: "no-store",
    });
    if (!res.ok) return { appleMusic: null, preview: null };
    const data: { results?: { trackViewUrl?: string; previewUrl?: string }[] } =
      await res.json();
    const result = data.results?.[0];
    return {
      appleMusic: forceHttps(result?.trackViewUrl),
      preview: forceHttps(result?.previewUrl),
    };
  } catch {
    return { appleMusic: null, preview: null };
  }
}

async function fetchYoutubeVideoId(artist: string, title: string): Promise<string | null> {
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
    if (!res.ok) return null;
    const data: { items?: { id?: { videoId?: string } }[] } = await res.json();
    return data.items?.[0]?.id?.videoId ?? null;
  } catch {
    return null;
  }
}

export async function getStreamingLinks(
  artist: string,
  title: string,
): Promise<StreamingLinks> {
  const query = encodeURIComponent(`${artist} ${title}`);
  const [itunes, youtubeVideoId] = await Promise.all([
    fetchItunesLinks(artist, title),
    fetchYoutubeVideoId(artist, title),
  ]);
  return {
    appleMusic: itunes.appleMusic,
    preview: itunes.preview,
    youtubeVideoId,
    spotify: `https://open.spotify.com/search/${query}`,
  };
}
