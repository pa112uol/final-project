"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type { SearchResult } from "../api/search/route";

export default function CompositionSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [chips, setChips] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!query.trim()) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        if (res.ok) {
          const data = await res.json();
          setResults(data.results ?? []);
          setOpen(true);
        }
      } catch {}
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  function addChip(result: SearchResult) {
    if (!chips.find((c) => c.mbid === result.mbid)) {
      setChips((prev) => [...prev, result]);
    }
    setQuery("");
    setResults([]);
    setOpen(false);
    inputRef.current?.focus();
  }

  function removeChip(mbid: string) {
    setChips((prev) => prev.filter((c) => c.mbid !== mbid));
  }

  function handleDiscover() {
    if (chips.length === 0) return;
    // Pass mbid + title + artist so the recommendations API can use them
    // without needing an extra MusicBrainz round-trip
    const seeds = chips.map((c) => ({ id: c.mbid, t: c.label, a: c.sub ?? "" }));
    router.push(`/tracks?q=${encodeURIComponent(JSON.stringify(seeds))}`);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-4 flex items-center">
          <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            const val = e.target.value;
            setQuery(val);
            if (!val.trim()) {
              setResults([]);
              setOpen(false);
            }
          }}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search for an artist or track…"
          className="w-full rounded-2xl border border-white/10 bg-white/5 py-4 pl-11 pr-4 text-sm text-slate-100 placeholder-slate-500 shadow-lg outline-none backdrop-blur-sm transition focus:border-violet-500/50 focus:bg-white/8 focus:ring-2 focus:ring-violet-500/20"
        />

        {open && results.length > 0 && (
          <ul className="absolute z-10 mt-2 w-full overflow-hidden rounded-2xl border border-white/10 bg-slate-900/95 shadow-2xl backdrop-blur-lg">
            {results.map((r) => (
              <li key={r.mbid}>
                <button
                  type="button"
                  onMouseDown={() => addChip(r)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm transition-colors hover:bg-white/5"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400 text-base">
                    ♪
                  </div>
                  <span className="truncate font-medium text-slate-100">{r.label}</span>
                  {r.sub && (
                    <span className="ml-auto shrink-0 text-xs text-slate-500">{r.sub}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <span
              key={chip.mbid}
              className="flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1.5 text-sm text-violet-200"
            >
              {chip.label}
              {chip.sub && (
                <span className="text-xs text-violet-400/60">— {chip.sub}</span>
              )}
              <button
                type="button"
                onClick={() => removeChip(chip.mbid)}
                className="ml-0.5 rounded-full p-0.5 text-violet-400 transition-colors hover:bg-violet-500/20 hover:text-violet-200"
                aria-label={`Remove ${chip.label}`}
              >
                <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={handleDiscover}
        disabled={chips.length === 0}
        className="flex items-center justify-center gap-2 self-stretch rounded-2xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-6 py-4 text-sm font-semibold text-white shadow-lg shadow-violet-900/30 transition hover:from-violet-500 hover:to-fuchsia-500 hover:shadow-violet-800/40 disabled:cursor-not-allowed disabled:opacity-30 disabled:shadow-none"
      >
        Discover tracks
      </button>
    </div>
  );
}
