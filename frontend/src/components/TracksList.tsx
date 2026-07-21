import { useState, useEffect } from "react";
import CoverArt from "./CoverArt";
import { FOCUS_RING } from "../lib/styles";

interface StreamingLinks {
  appleMusic: string | null;
  preview: string | null;
  youtubeVideoId: string | null;
  spotify: string;
  artwork: { small: string; medium: string; large: string } | null;
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
}

const LINK_CLASS = `text-blue underline hover:text-blue-dark transition-colors rounded ${FOCUS_RING}`;

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

function albumName(track: Track): string | null {
  return track.releases[0]?.title || null;
}

function TrackCard({ track }: { track: Track }) {
  const year = releaseYear(track);
  const duration = fmtDuration(track.durationMs);
  const album = albumName(track);
  return (
    <div className="bg-bg-surface rounded-xl p-4 space-y-3">
      <div className="flex gap-3 items-start">
        {track.mbid && (
          <CoverArt
            mbid={track.mbid}
            artworkUrl={track.streaming.artwork?.medium}
            className="w-16 h-16 rounded-lg"
          />
        )}
        <div className="min-w-0">
          <h3 className="font-semibold text-lg leading-tight text-text-primary">
            {track.title}
          </h3>
          <p className="text-text-secondary text-sm">
            {track.artist}
            {album && <span className="ml-2 text-text-muted">{album}</span>}
            {year && <span className="ml-2 text-text-muted">{year}</span>}
            {duration && (
              <span className="ml-2 text-text-muted">{duration}</span>
            )}
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
            className={LINK_CLASS}
          >
            Apple Music
          </a>
        )}
        <a
          href={track.streaming.spotify}
          target="_blank"
          rel="noopener noreferrer"
          className={LINK_CLASS}
        >
          Spotify
        </a>
        {track.mbid && (
          <a
            href={`https://musicbrainz.org/recording/${track.mbid}`}
            target="_blank"
            rel="noopener noreferrer"
            className={LINK_CLASS}
          >
            MusicBrainz
          </a>
        )}
      </div>

      {track.tags.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {track.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 rounded-full bg-bg-raised text-text-secondary text-xs"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="text-xs text-text-muted flex gap-3">
        <span>Relevance {(track.relevanceScore * 100).toFixed(1)}%</span>
        <span>Novelty {(track.noveltyScore * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

export default function TracksList({ url }: TracksListProps) {
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
      <div className="space-y-4" aria-busy="true" aria-label="Loading tracks">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="bg-bg-surface rounded-xl p-4 h-24 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="bg-bg-raised border border-red rounded-xl p-4 text-text-primary flex gap-3 items-start"
      >
        <span
          className="text-red text-lg leading-none mt-0.5"
          aria-hidden="true"
        >
          ⚠
        </span>
        <div>
          <p className="font-semibold">Error loading tracks</p>
          <p className="text-sm mt-1 text-text-secondary">{error}</p>
        </div>
      </div>
    );
  }

  if (!tracks || tracks.length === 0) {
    return (
      <div className="text-center text-text-muted py-12">
        No tracks found. Try different seeds or adjust novelty.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-text-secondary text-sm">{tracks.length} tracks</p>
      </div>
      {tracks.map((t) => (
        <TrackCard key={t.mbid || `${t.title}-${t.artist}`} track={t} />
      ))}
    </div>
  );
}

