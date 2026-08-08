import { useState, useEffect } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
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
  relevanceScore?: number;
  noveltyScore?: number;
  selectionReason?: SelectionReason;
  tags?: string[];
}

// Why the track won its slot. "top_match" means it simply had the best score
// among the candidates, "for_variety" means the diversity re-ranker
// lifted it past higher scoring but more similar tracks
type SelectionReason = "top_match" | "for_variety";

// Shape of a GET /api/recording/ response, used to patch a track once its
// canonical recording has resolved
interface RecordingPatch {
  mbid: string | null;
  durationMs: number | null;
  firstReleaseDate: string | null;
  releases: { mbid: string; title: string; date?: string }[];
}

interface TracksListProps {
  url: string;
  novelty?: number;
  // When set, tracks with no release info are resolved one at a time via
  // /api/recording/ after the list renders, patching in mbid/duration/album.
  resolveRecordings?: boolean;
}

const MAX_TAGS = 5;

// An unweighted bar still has to read as present rather than missing, so the
// fade stops well short of invisible
const MIN_BAR_OPACITY = 0.35;
// The slider steps in 0.01, so anything below this is exactly zero weight
const UNWEIGHTED_THRESHOLD = 0.005;

function barOpacity(weight: number): number {
  return MIN_BAR_OPACITY + (1 - MIN_BAR_OPACITY) * weight;
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

function albumName(track: Track): string | null {
  return track.releases[0]?.title || null;
}

function releaseMbid(track: Track): string | undefined {
  return track.releases[0]?.mbid || undefined;
}

// Stable identity for a track that survives its mbid changing underneath it
// (a lazily resolved recording can replace a stale source-supplied mbid).
function trackKey(track: { title: string; artist: string }): string {
  return `${track.title.toLowerCase()}|||${track.artist.toLowerCase()}`;
}

// The outbound links are in a consistent order: Apple Music, Spotify, MusicBrainz.
// The MusicBrainz link is omitted while the mbid is pending resolution
function outboundLinks(
  track: Track,
  pending: boolean,
): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = [];
  if (track.streaming.appleMusic)
    links.push({ label: "Apple Music", href: track.streaming.appleMusic });
  if (track.streaming.spotify)
    links.push({ label: "Spotify", href: track.streaming.spotify });
  if (track.mbid && !pending)
    links.push({
      label: "MusicBrainz",
      href: `https://musicbrainz.org/recording/${track.mbid}`,
    });
  return links;
}

// Applies a /api/recording/ patch to a track without wiping fields the
// candidate already supplied. A null patch field must not clobber an existing value
function mergeRecording(track: Track, patch: RecordingPatch): Track {
  return {
    ...track,
    mbid: patch.mbid || track.mbid,
    durationMs: patch.durationMs ?? track.durationMs,
    firstReleaseDate: patch.firstReleaseDate ?? track.firstReleaseDate,
    releases: patch.releases.length ? patch.releases : track.releases,
  };
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

// Only the variety picks get a badge. A "top match" card is already explained
// by its bars being the highest of what was left, so labelling all ten would
// bury the two that genuinely need it: the ones ranked above a card with
// visibly better bars, which otherwise read as a sorting bug
function SelectionBadge({ reason }: { reason?: SelectionReason }) {
  if (reason !== "for_variety") return null;
  return (
    <div className="mb-3">
      <span
        className={`${CHIP_SHAPE} inline-block text-[11px] uppercase tracking-[0.06em] text-text-muted bg-fill border border-border-subtle`}
        title="Ranked above higher-scoring tracks because it adds something the picks above it don't"
      >
        Added for variety
        <span className="sr-only">
          : ranked above higher-scoring tracks because it adds something the
          picks above it don&rsquo;t
        </span>
      </span>
    </div>
  );
}

// The two things about this list that the cards cannot explain on their own,
// stated once at the top rather than repeated per card: both are properties of
// the whole ordering, not of any one track. Each clause appears only when it
// has something to explain, so the note is silent on an unremarkable list.
function OrderingNote({
  novelty,
  hasVarietyPicks,
}: {
  novelty: number;
  hasVarietyPicks: boolean;
}) {
  const relevanceInert = 1 - novelty < UNWEIGHTED_THRESHOLD;
  const noveltyInert = novelty < UNWEIGHTED_THRESHOLD;
  const [ranked, ignored] = noveltyInert
    ? ["relevance", "Novelty"]
    : ["novelty", "Relevance"];
  const showWeighting = relevanceInert || noveltyInert;
  if (!showWeighting && !hasVarietyPicks) return null;

  return (
    <p className="text-[13px] text-text-muted mb-5 leading-relaxed">
      {showWeighting && (
        <>
          Ranked on{" "}
          <span className="text-text-primary font-semibold">{ranked}</span>{" "}
          only.
          {" " + ignored} scores are shown below but did not affect this
          ordering.{" "}
        </>
      )}
      {hasVarietyPicks && (
        <>
          Tracks marked{" "}
          <span className="text-text-primary font-semibold">
            Added for Variety
          </span>{" "}
          ranked above higher-scoring ones because they bring something the
          picks above them don&rsquo;t.
        </>
      )}
    </p>
  );
}

// `weight` is how much this score counted toward the ranking, 0–1, and the bar
// is dimmed to match. The weight is a property of the query rather than the
// track, so it stays out of the visible label: printing it on every card said
// the same several times
function StatBar({
  label,
  pct,
  weight,
  barClassName,
}: {
  label: string;
  pct: number;
  weight: number;
  barClassName: string;
}) {
  const rounded = Math.max(0, Math.min(100, pct));
  const unweighted = weight < UNWEIGHTED_THRESHOLD;
  return (
    <div
      className="flex-1"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(rounded)}
      aria-valuetext={
        unweighted
          ? `${Math.round(rounded)} percent, not weighted in this ranking`
          : `${Math.round(rounded)} percent`
      }
    >
      <div className="flex justify-between text-xs text-text-muted mb-1.5">
        <span>{label}</span>
        <span>{pct.toFixed(pct % 1 === 0 ? 0 : 1)}%</span>
      </div>
      <div
        className="h-[5px] rounded-[3px] bg-fill overflow-hidden"
        style={{ opacity: barOpacity(weight) }}
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

function TrackCard({
  track,
  novelty,
  pending = false,
}: {
  track: Track;
  novelty: number;
  pending?: boolean;
}) {
  const year = releaseYear(track);
  const duration = fmtDuration(track.durationMs);
  const album = albumName(track);
  const links = outboundLinks(track, pending);
  const tags = (track.tags ?? []).slice(0, MAX_TAGS);
  // Unranked tracks have nothing to say on either axis, so the whole footer
  // goes rather than rendering empty bars
  const scored =
    track.relevanceScore !== undefined && track.noveltyScore !== undefined;

  return (
    <article className="bg-bg-surface border border-border-subtle rounded-card p-[22px] shadow-card">
      <div className="flex gap-4 items-start mb-5">
        {track.mbid && (
          <CoverArt
            mbid={track.mbid}
            artworkUrl={track.streaming.artwork?.medium}
            className="w-16 h-16 rounded-media"
            pending={pending}
            releaseMbid={releaseMbid(track)}
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
          {!album && !year && pending && (
            <p
              className="mt-[3px] h-[17px] w-32 rounded bg-fill animate-pulse"
              aria-hidden="true"
            />
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

      {scored && (
        <div className="mt-[18px] pt-4 border-t border-border-subtle">
          <SelectionBadge reason={track.selectionReason} />
          <div className="flex gap-7">
            {/* The blend is (1 - novelty) * relevance + novelty * obscurity,
                so those coefficients are exactly each bar's weight */}
            <StatBar
              label="Relevance"
              pct={track.relevanceScore! * 100}
              weight={1 - novelty}
              barClassName="bg-amber"
            />
            <StatBar
              label="Novelty"
              pct={track.noveltyScore! * 100}
              weight={novelty}
              barClassName="bg-text-dim"
            />
          </div>
        </div>
      )}
    </article>
  );
}

// Resolves one track's canonical recording, patching it into the list in
// place. Best-effort: a failed lookup leaves the track as it arrived
async function resolveOneTrack(
  track: Track,
  key: string,
  cancelled: () => boolean,
  setTracks: Dispatch<SetStateAction<Track[] | null>>,
  setPendingKeys: Dispatch<SetStateAction<Set<string>>>,
) {
  try {
    const params = new URLSearchParams({
      title: track.title,
      artist: track.artist,
    });
    if (track.mbid) params.set("mbid", track.mbid);
    const res = await fetch(`/api/recording/?${params.toString()}`);
    if (!res.ok || cancelled()) return;
    const patch: RecordingPatch = await res.json();
    if (cancelled()) return;
    setTracks((prev) =>
      prev
        ? prev.map((t) => (trackKey(t) === key ? mergeRecording(t, patch) : t))
        : prev,
    );
    // Pending clears only on a confirmed resolution, not a failed lookup
    setPendingKeys((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  } catch {
    // Leave the track pending and move on to the next one
  }
}

export default function TracksList({
  url,
  novelty = 0,
  resolveRecordings = false,
}: TracksListProps) {
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTracks(null);
    setPendingKeys(new Set());

    async function run() {
      let list: Track[];
      try {
        const res = await fetch(url);
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || "Request failed");
        }
        const data = await res.json();
        list = data.tracks || [];
      } catch (err) {
        if (!cancelled) setError(String(err));
        return;
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (cancelled) return;
      setTracks(list);

      if (!resolveRecordings) return;
      const targets = list.filter((t) => t.releases.length === 0 && t.title);
      if (targets.length === 0) return;
      setPendingKeys(new Set(targets.map(trackKey)));

      // Sequential, not parallel: requests share the same rate-limited MusicBrainz call anyway
      for (const t of targets) {
        if (cancelled) return;
        await resolveOneTrack(
          t,
          trackKey(t),
          () => cancelled,
          setTracks,
          setPendingKeys,
        );
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [url, resolveRecordings]);

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

  // Unranked results (the random page) have no ordering to explain
  const ranked = tracks.some((t) => t.relevanceScore !== undefined);
  const hasVarietyPicks = tracks.some(
    (t) => t.selectionReason === "for_variety",
  );

  return (
    <div>
      {ranked && (
        <OrderingNote novelty={novelty} hasVarietyPicks={hasVarietyPicks} />
      )}
      <div className="space-y-5">
        {tracks.map((t, i) => (
          <TrackCard
            // Index-qualified since trackKey alone can collide for /api/random/ results
            key={`${trackKey(t)}|||${i}`}
            track={t}
            novelty={novelty}
            pending={pendingKeys.has(trackKey(t))}
          />
        ))}
      </div>
    </div>
  );
}

