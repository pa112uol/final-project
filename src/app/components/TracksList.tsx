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

function TrackCard({ track }: { track: Track }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-zinc-900 dark:text-zinc-100">
            {track.title}
          </h2>
          <p className="text-sm text-zinc-500">{track.artist}</p>
        </div>
        <div className="shrink-0 text-right text-xs text-zinc-400">
          {track.firstReleaseDate && (
            <p>{track.firstReleaseDate.slice(0, 4)}</p>
          )}
          {track.durationMs && <p>{formatDuration(track.durationMs)}</p>}
        </div>
      </div>

      {track.streaming.youtubeVideoId && (
        <iframe
          className="w-full rounded-lg"
          height={220}
          src={`https://www.youtube.com/embed/${track.streaming.youtubeVideoId}`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      )}

      {!track.streaming.youtubeVideoId && track.streaming.preview && (
        <audio controls className="w-full" src={track.streaming.preview} />
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {track.streaming.appleMusic && (
          <a
            href={track.streaming.appleMusic}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-zinc-100 px-3 py-1 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            Apple Music
          </a>
        )}
        <a
          href={track.streaming.spotify}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-full bg-zinc-100 px-3 py-1 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
        >
          Spotify
        </a>
        <a
          href={`https://musicbrainz.org/recording/${track.mbid}`}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-full bg-zinc-100 px-3 py-1 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
        >
          MusicBrainz
        </a>
      </div>
    </div>
  );
}

export default function TracksList() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchTracks() {
    try {
      const res = await fetch("/api/tracks");
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
    async function loadTracks() {
      await fetchTracks();
    }

    loadTracks();
  }, []);

  function handleShuffle() {
    setLoading(true);
    setError(null);
    fetchTracks();
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
          Random Tracks
        </h1>
        <button
          onClick={handleShuffle}
          disabled={loading}
          className="rounded-full bg-zinc-900 px-4 py-2 text-sm text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {loading ? "Loading…" : "Shuffle"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {loading && (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-64 animate-pulse rounded-xl bg-zinc-100 dark:bg-zinc-800"
            />
          ))}
        </div>
      )}

      {!loading && (
        <div className="flex flex-col gap-4">
          {tracks.map((track) => (
            <TrackCard key={track.mbid} track={track} />
          ))}
        </div>
      )}
    </>
  );
}

