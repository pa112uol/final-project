import { useState, useEffect, useRef, useCallback } from "react";
import { ArrowRight, Shuffle } from "lucide-react";
import CoverArt from "./CoverArt";
import NoveltySlider, { noveltyPct } from "./NoveltySlider";
import MoodPicker from "./MoodPicker";
import Field from "./Field";
import { FOCUS_RING, FOCUS_RING_INSET } from "../lib/styles";
import type { Seed } from "../lib/types";

interface SearchResult {
  type: "track";
  mbid: string;
  label: string;
  sub?: string;
  album?: string | null;
  releaseType?: string | null;
  year?: string | null;
}

interface CompositionSearchProps {
  onDiscover: (seeds: Seed[], mood: string | null, novelty: number) => void;
  onRandom?: () => void;
}

const DEFAULT_MAX_SEED_TRACKS = 5;

// Read the max seed tracks from the environment variable,
// falling back to the default if not set or invalid
function readMaxSeedTracks(): number {
  const raw = import.meta.env.VITE_MAX_SEED_TRACKS;
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_MAX_SEED_TRACKS;
}

const MAX_SEED_TRACKS = readMaxSeedTracks();

export default function CompositionSearch({
  onDiscover,
  onRandom,
}: CompositionSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [chips, setChips] = useState<Seed[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [mood, setMood] = useState<string | null>(null);
  const [novelty, setNovelty] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const limitReached = chips.length >= MAX_SEED_TRACKS;

  useEffect(() => {
    if (!query.trim() || limitReached) return;

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/?q=${encodeURIComponent(query)}`);
        if (cancelled) return;
        if (!res.ok) {
          setResults([]);
          setOpen(false);
          setLoading(false);
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        const fetched = data.results || [];
        setResults(fetched);
        setOpen(fetched.length > 0 || query.trim().length > 0);
        setActiveIndex(-1);
        setLoading(false);
      } catch {
        if (cancelled) return;
        setResults([]);
        setOpen(false);
        setLoading(false);
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, limitReached]);

  // Close dropdown on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex < 0 || !listRef.current) return;
    const item = listRef.current.children[activeIndex] as
      | HTMLElement
      | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const addChip = useCallback(
    (result: SearchResult) => {
      const alreadyAdded = chips.find((c) => c.mbid === result.mbid);
      if (!alreadyAdded && chips.length >= MAX_SEED_TRACKS) return;
      if (!alreadyAdded) {
        setChips((prev) => [
          ...prev,
          { mbid: result.mbid, title: result.label, artist: result.sub || "" },
        ]);
      }
      setQuery("");
      setOpen(false);
      setActiveIndex(-1);
      inputRef.current?.focus();
    },
    [chips],
  );

  function removeChip(mbid: string) {
    setChips((prev) => prev.filter((c) => c.mbid !== mbid));
    inputRef.current?.focus();
  }

  function discover() {
    if (chips.length > 0) onDiscover(chips, mood, novelty);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = activeIndex >= 0 ? results[activeIndex] : results[0];
      if (target) addChip(target);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  function clearQuery() {
    setQuery("");
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
    inputRef.current?.focus();
  }

  const showDropdown =
    open && !loading && query.trim().length > 0 && !limitReached;

  return (
    <div className="space-y-6">
      <Field
        label="Pick a track"
        hint={
          limitReached
            ? `Limit reached (${MAX_SEED_TRACKS} max)`
            : `${chips.length}/${MAX_SEED_TRACKS}`
        }
      >
        <div className="relative" ref={containerRef}>
          <div className="relative">
            <input
              ref={inputRef}
              type="text"
              value={query}
              disabled={limitReached}
              onChange={(e) => {
                const val = e.target.value;
                setQuery(val);
                if (!val.trim()) {
                  setResults([]);
                  setOpen(false);
                  setLoading(false);
                  setActiveIndex(-1);
                } else {
                  setLoading(true);
                }
              }}
              onKeyDown={handleKeyDown}
              onFocus={() => {
                if (results.length > 0) setOpen(true);
              }}
              placeholder={
                limitReached
                  ? `Maximum ${MAX_SEED_TRACKS} seed tracks added`
                  : "Search for artist - track..."
              }
              autoComplete="off"
              spellCheck={false}
              className={`w-full bg-bg-surface text-text-primary rounded-lg px-4 py-3 pr-10 outline-none border border-border-default disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
            />
            {loading && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2">
                <svg
                  className="animate-spin h-4 w-4 text-amber"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
              </span>
            )}
            {!loading && query && (
              <button
                onClick={clearQuery}
                className={`absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary transition-colors rounded ${FOCUS_RING}`}
                tabIndex={-1}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>

          {showDropdown && (
            <ul
              ref={listRef}
              className="absolute z-10 w-full bg-bg-surface border border-border-default rounded-lg mt-1 shadow-xl max-h-64 overflow-y-auto"
              role="listbox"
            >
              {results.length === 0 ? (
                <li className="px-4 py-3 text-text-muted text-sm flex items-center gap-2">
                  <span className="text-red" aria-hidden="true">
                    ⚠
                  </span>
                  <span>No results for &ldquo;{query}&rdquo;</span>
                </li>
              ) : (
                results.map((r, i) => {
                  const isActive = i === activeIndex;
                  const isAdded = chips.some((c) => c.mbid === r.mbid);
                  const meta = [r.sub, r.album, r.releaseType, r.year]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <li key={r.mbid} role="option" aria-selected={isActive}>
                      <button
                        onMouseDown={(e) => {
                          e.preventDefault();
                          addChip(r);
                        }}
                        onMouseEnter={() => setActiveIndex(i)}
                        className={`w-full text-left px-4 py-2.5 transition-colors flex items-center justify-between gap-2 ${FOCUS_RING_INSET} ${
                          isActive ? "bg-bg-raised" : "hover:bg-bg-raised"
                        }`}
                      >
                        <span className="flex flex-col min-w-0">
                          <span className="font-medium truncate text-text-primary">
                            {r.label}
                          </span>
                          {meta && (
                            <span className="text-text-secondary text-sm truncate">
                              {meta}
                            </span>
                          )}
                        </span>
                        {isAdded && (
                          <span className="shrink-0 text-xs text-amber font-semibold">
                            ✓ added
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          )}
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {chips.map((c) => (
              <span
                key={c.mbid}
                className="inline-flex items-center gap-1.5 bg-bg-raised border border-border-default text-text-primary rounded-full pl-1 pr-3 py-1 text-sm"
              >
                <CoverArt mbid={c.mbid} className="w-6 h-6 rounded-full" />
                <span className="font-medium">{c.title}</span>
                {c.artist && (
                  <span className="text-text-secondary font-normal">
                    · {c.artist}
                  </span>
                )}
                <button
                  onClick={() => removeChip(c.mbid)}
                  className={`ml-1 hover:text-red transition-colors leading-none rounded ${FOCUS_RING}`}
                  aria-label={`Remove ${c.title}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </Field>

      <Field label="Mood">
        <MoodPicker value={mood} onChange={setMood} />
      </Field>

      <Field label="Novelty" hint={`${noveltyPct(novelty)} / 100`}>
        <NoveltySlider value={novelty} onChange={setNovelty} />
      </Field>

      <button
        onClick={discover}
        disabled={chips.length === 0}
        className={`w-full bg-amber hover:bg-amber-dark disabled:opacity-40 disabled:cursor-not-allowed text-bg-base font-semibold rounded-lg px-4 py-3 transition-colors ${FOCUS_RING}`}
      >
        Find Similar <ArrowRight className="inline-block ml-1 w-4 h-4" />
      </button>

      {onRandom && (
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px bg-border-default" />
          <span className="text-xs text-text-muted uppercase tracking-widest">
            or
          </span>
          <div className="flex-1 h-px bg-border-default" />
        </div>
      )}

      {onRandom && (
        <button
          onClick={onRandom}
          className={`w-full border border-border-default hover:border-text-muted text-text-secondary hover:text-text-primary font-semibold rounded-lg px-4 py-3 transition-colors ${FOCUS_RING}`}
        >
          <Shuffle className="inline-block mr-2 w-4 h-4" /> Surprise Me
        </button>
      )}
    </div>
  );
}

