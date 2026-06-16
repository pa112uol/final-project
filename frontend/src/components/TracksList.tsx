import { useState, useEffect } from "react";

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
  relevanceScore: number;
  noveltyScore: number;
  tags: string[];
}

interface TracksListProps {
  url: string;
  onRefresh: () => void;
}

function fmtDuration(ms: number | null): string {
  if (!ms) return "";
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function releaseYear(track: Track): string | null {
  const date =
    track.firstReleaseDate || track.releases.find((r) => r.date)?.date || null;
  return date ? date.slice(0, 4) : null;
}

function CoverArt({ releaseMbid }: { releaseMbid: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/coverart/?mbid=${encodeURIComponent(releaseMbid)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => { if (!cancelled) setUrl(data.url); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [releaseMbid]);

  if (loading) {
    return <div className="w-16 h-16 rounded-lg bg-gray-700 animate-pulse flex-shrink-0" />;
  }
  if (!url) {
    return (
      <div className="w-16 h-16 rounded-lg bg-gray-700 flex items-center justify-center flex-shrink-0">
        <svg className="w-6 h-6 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="Album art"
      className="w-16 h-16 rounded-lg object-cover flex-shrink-0"
    />
  );
}

function TrackCard({ track }: { track: Track }) {
  const year = releaseYear(track);
  const duration = fmtDuration(track.durationMs);
  return (
    <div className="bg-gray-800 rounded-xl p-4 space-y-3">
      <div className="flex gap-3 items-start">
        {track.mbid && <CoverArt releaseMbid={track.mbid} />}
        <div className="min-w-0">
          <h3 className="font-semibold text-lg leading-tight">{track.title}</h3>
          <p className="text-gray-400 text-sm">
            {track.artist}
            {year && <span className="ml-2 text-gray-500">{year}</span>}
            {duration && <span className="ml-2 text-gray-500">{duration}</span>}
          </p>
        </div>
      </div>

      {track.streaming.youtubeVideoId && (
        <div className="aspect-video rounded-lg overflow-hidden">
          <iframe
            src={`https://www.youtube.com/embed/${track.streaming.youtubeVideoId}`}
            title={track.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="w-full h-full"
          />
        </div>
      )}

      {track.streaming.preview && !track.streaming.youtubeVideoId && (
        <audio controls src={track.streaming.preview} className="w-full" />
      )}

      <div className="flex flex-wrap gap-2 text-sm">
        {track.streaming.appleMusic && (
          <a
            href={track.streaming.appleMusic}
            target="_blank"
            rel="noopener noreferrer"
            className="text-pink-400 hover:text-pink-300"
          >
            Apple Music
          </a>
        )}
        <a
          href={track.streaming.spotify}
          target="_blank"
          rel="noopener noreferrer"
          className="text-green-400 hover:text-green-300"
        >
          Spotify
        </a>
        {track.mbid && (
          <a
            href={`https://musicbrainz.org/recording/${track.mbid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-400 hover:text-gray-300"
          >
            MusicBrainz
          </a>
        )}
      </div>

      {track.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {track.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 rounded-full bg-gray-700 text-gray-300 text-xs"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="text-xs text-gray-600 flex gap-3">
        <span>Relevance {(track.relevanceScore * 100).toFixed(0)}%</span>
        <span>Novelty {(track.noveltyScore * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

export default function TracksList({ url, onRefresh }: TracksListProps) {
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTracks(null);
    fetch(url)
      .then((res) => {
        if (!res.ok)
          return res
            .json()
            .then((d) => Promise.reject(d.error || "Request failed"));
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setTracks(data.tracks || []);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="bg-gray-800 rounded-xl p-4 h-24 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900 rounded-xl p-4 text-red-200">
        <p className="font-semibold">Error</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!tracks || tracks.length === 0) {
    return (
      <div className="text-center text-gray-500 py-12">
        No tracks found. Try different seeds or adjust novelty.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-gray-400 text-sm">{tracks.length} tracks</p>
        <button
          onClick={onRefresh}
          className="text-sm text-indigo-400 hover:text-indigo-300"
        >
          Shuffle
        </button>
      </div>
      {tracks.map((t) => (
        <TrackCard key={t.mbid || `${t.title}-${t.artist}`} track={t} />
      ))}
    </div>
  );
}
