import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import CoverArt from "./CoverArt";
import { CHIP_SHAPE, FOCUS_RING, FOCUS_RING_INSET } from "../lib/styles";

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

const MAX_TAGS = 5;

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

// The outbound links are in a consistent order: Apple Music, Spotify, MusicBrainz.
function outboundLinks(track: Track): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = [];
  if (track.streaming.appleMusic)
    links.push({ label: "Apple Music", href: track.streaming.appleMusic });
  if (track.streaming.spotify)
    links.push({ label: "Spotify", href: track.streaming.spotify });
  if (track.mbid)
    links.push({
      label: "MusicBrainz",
      href: `https://musicbrainz.org/recording/${track.mbid}`,
    });
  return links;
}

function LinkChip({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${CHIP_SHAPE} inline-flex items-center gap-1.5 text-[13px] bg-fill border border-border-default text-text-primary hover:bg-fill-strong transition-colors ${FOCUS_RING}`}
    >
      {children}
      <ArrowUpRight className="w-3.5 h-3.5" aria-hidden="true" />
    </a>
  );
}

function StatBar({
  label,
  pct,
  barClassName,
}: {
  label: string;
  pct: number;
  barClassName: string;
}) {
  const rounded = Math.max(0, Math.min(100, pct));
  return (
    <div
      className="flex-1"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(rounded)}
    >
      <div className="flex justify-between text-xs text-text-muted mb-1.5">
        <span>{label}</span>
        <span>{pct.toFixed(pct % 1 === 0 ? 0 : 1)}%</span>
      </div>
      <div
        className="h-[5px] rounded-[3px] bg-fill overflow-hidden"
        aria-hidden="true"
      >
        <div
          className={`h-full rounded-[3px] ${barClassName}`}
          style={{ width: `${rounded}%` }}
        />
      </div>
    </div>
  );
}

// The YouTube player is only mounted when the user clicks the play button.
// Before that, a thumbnail is shown with a play button overlay,
// reducing the number of iframes on the page and improving performance
function YouTubePlayer({ videoId, title }: { videoId: string; title: string }) {
  const [playing, setPlaying] = useState(false);

  return (
    <div className="relative w-full aspect-video rounded-media overflow-hidden bg-black">
      {playing ? (
        <iframe
          src={`https://www.youtube.com/embed/${videoId}?autoplay=1`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          className="absolute inset-0 w-full h-full"
        />
      ) : (
        <>
          <button
            type="button"
            onClick={() => setPlaying(true)}
            aria-label={`Play ${title}`}
            className={`group absolute inset-0 w-full h-full cursor-pointer ${FOCUS_RING_INSET}`}
          >
            <img
              src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
              alt=""
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover"
            />
            <span
              className="absolute inset-0 flex items-center justify-center"
              aria-hidden="true"
            >
              <span className="w-16 h-16 rounded-full bg-black/55 border-2 border-white/85 flex items-center justify-center transition-colors group-hover:bg-black/75">
                <svg
                  viewBox="0 0 22 26"
                  fill="#fff"
                  className="w-[22px] h-[26px] ml-1"
                >
                  <polygon points="0,0 22,13 0,26" />
                </svg>
              </span>
            </span>
          </button>
          <a
            href={`https://www.youtube.com/watch?v=${videoId}`}
            target="_blank"
            rel="noopener noreferrer"
            className={`absolute right-3 bottom-3 z-10 inline-flex items-center gap-1.5 rounded-chip bg-black/60 px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-black/80 transition-colors ${FOCUS_RING}`}
          >
            Watch on YouTube
            <ArrowUpRight className="w-3.5 h-3.5" aria-hidden="true" />
          </a>
        </>
      )}
    </div>
  );
}

function TrackCard({ track }: { track: Track }) {
  const year = releaseYear(track);
  const duration = fmtDuration(track.durationMs);
  const album = albumName(track);
  const links = outboundLinks(track);
  const tags = track.tags.slice(0, MAX_TAGS);

  return (
    <article className="bg-bg-surface border border-border-subtle rounded-card p-[22px] shadow-card">
      <div className="flex gap-4 items-start mb-5">
        {track.mbid && (
          <CoverArt
            mbid={track.mbid}
            artworkUrl={track.streaming.artwork?.medium}
            className="w-16 h-16 rounded-media"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-[21px] font-extrabold tracking-[-0.01em] leading-tight text-text-primary truncate">
              {track.title}
            </h3>
            {duration && (
              <span className="text-[13px] text-text-muted flex-shrink-0">
                {duration}
              </span>
            )}
          </div>
          <p className="text-[15px] font-semibold text-text-primary mt-[5px]">
            {track.artist}
          </p>
          {(album || year) && (
            <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-text-muted mt-[3px]">
              {album && <span>{album}</span>}
              {album && year && (
                <span className="text-text-dim" aria-hidden="true">
                  &middot;
                </span>
              )}
              {year && <span>{year}</span>}
            </p>
          )}
        </div>
      </div>

      {track.streaming.youtubeVideoId && (
        <YouTubePlayer
          videoId={track.streaming.youtubeVideoId}
          title={track.title}
        />
      )}

      {track.streaming.preview && !track.streaming.youtubeVideoId && (
        <audio controls src={track.streaming.preview} className="w-full" />
      )}

      {links.length > 0 && (
        <div className="flex flex-wrap items-center gap-2.5 mt-[18px]">
          {links.map((link) => (
            <LinkChip key={link.label} href={link.href}>
              {link.label}
            </LinkChip>
          ))}
        </div>
      )}

      {tags.length > 0 && (
        <ul className="flex flex-wrap gap-2 mt-3">
          {tags.map((tag) => (
            <li
              key={tag}
              className={`${CHIP_SHAPE} text-xs text-amber-muted bg-amber-soft`}
            >
              {tag}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-7 mt-[18px] pt-4 border-t border-border-subtle">
        <StatBar
          label="Relevance"
          pct={track.relevanceScore * 100}
          barClassName="bg-amber"
        />
        <StatBar
          label="Novelty"
          pct={track.noveltyScore * 100}
          barClassName="bg-text-dim"
        />
      </div>
    </article>
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
      <div className="space-y-5" aria-busy="true" aria-label="Loading tracks">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="bg-bg-surface border border-border-subtle rounded-card h-44 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="bg-bg-surface border border-red rounded-card p-[22px] text-text-primary flex gap-3 items-start"
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
    <div className="space-y-5">
      {tracks.map((t) => (
        <TrackCard key={t.mbid || `${t.title}-${t.artist}`} track={t} />
      ))}
    </div>
  );
}

