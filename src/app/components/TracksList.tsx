"use client";

import { useEffect, useState } from "react";

interface Release {
  mbid: string;
  title: string;
  date?: string;
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
  releases: Release[];
  streaming: StreamingLinks;
}

function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function TrackCard({ track, index }: { track: Track; index: number }) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-white/8 bg-white/[0.03] p-6 transition-all hover:border-white/12 hover:bg-white/[0.05]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 text-sm font-bold text-violet-400">
            {index + 1}
          </div>
          <div>
            <h2 className="font-semibold leading-snug text-slate-100">
              {track.title}
            </h2>
            <p className="mt-0.5 text-sm text-slate-400">{track.artist}</p>
          </div>
        </div>
        <div className="shrink-0 text-right text-xs text-slate-500">
          {track.firstReleaseDate && (
            <p className="font-medium">{track.firstReleaseDate.slice(0, 4)}</p>
          )}
          {track.durationMs && (
            <p className="mt-0.5">{formatDuration(track.durationMs)}</p>
          )}
        </div>
      </div>

      {track.streaming.youtubeVideoId && (
        <div className="overflow-hidden rounded-xl">
          <iframe
            className="w-full"
            height={220}
            src={`https://www.youtube.com/embed/${track.streaming.youtubeVideoId}`}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      )}

      {track.streaming.preview && (
        <audio controls className="w-full" src={track.streaming.preview} />
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {track.streaming.appleMusic && (
          <a
            href={track.streaming.appleMusic}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-full border border-rose-500/20 bg-rose-500/10 px-3 py-1.5 text-rose-300 transition-colors hover:bg-rose-500/20"
          >
            Apple Music
          </a>
        )}
        <a
          href={track.streaming.spotify}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-full border border-green-500/20 bg-green-500/10 px-3 py-1.5 text-green-300 transition-colors hover:bg-green-500/20"
        >
          Spotify
        </a>
        {track.mbid && (
          <a
            href={`https://musicbrainz.org/recording/${track.mbid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-full border border-slate-500/20 bg-slate-500/10 px-3 py-1.5 text-slate-400 transition-colors hover:bg-slate-500/20"
          >
            MusicBrainz
          </a>
        )}
      </div>
    </div>
  );
}

interface TracksListProps {
  url?: string;
  mode?: "random" | "recommendations";
}

export default function TracksList({
  url = "/api/tracks",
  mode = "random",
}: TracksListProps) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchTracks() {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to load tracks");
      const data = await res.json();
      setTracks(data.tracks);
      setError(null);
    } catch {
      setError("Could not load tracks. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchTracks();
    // fetchTracks reads `url` from the closure; re-runs whenever url changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  function handleShuffle() {
    setLoading(true);
    setError(null);
    fetchTracks();
  }

  const isRecommendations = mode === "recommendations";
  const title = isRecommendations ? "Recommended for You" : "Discovered tracks";
  const buttonLabel = isRecommendations ? "Refresh" : "Shuffle";

  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{title}</h1>
          {!loading && tracks.length > 0 && (
            <p className="mt-1 text-sm text-slate-500">
              {tracks.length} tracks found
            </p>
          )}
        </div>
        <button
          onClick={handleShuffle}
          disabled={loading}
          className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-slate-300 transition-all hover:bg-white/10 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          {loading ? "Loading…" : buttonLabel}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-64 animate-pulse rounded-2xl border border-white/5 bg-white/[0.03]"
            />
          ))}
        </div>
      )}

      {!loading && tracks.length === 0 && !error && (
        <p className="text-sm text-slate-500">
          No tracks found. Try a different seed track or mood.
        </p>
      )}

      {!loading && tracks.length > 0 && (
        <div className="flex flex-col gap-4">
          {tracks.map((track, i) => (
            <TrackCard key={track.mbid || `${track.title}-${i}`} track={track} index={i} />
          ))}
        </div>
      )}
    </>
  );
}
