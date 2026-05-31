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
    const seeds = chips.map((c) => ({ id: c.mbid, t: c.label, a: c.sub ?? "" }));
    router.push(`/tracks?q=${encodeURIComponent(JSON.stringify(seeds))}`);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="relative">
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
          className="w-full rounded-lg border border-gray-300 bg-white px-4 py-3 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 dark:border-gray-600 dark:bg-gray-800 dark:text-white dark:focus:border-blue-400"
        />

        {open && results.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
            {results.map((r) => (
              <li key={r.mbid}>
                <button
                  type="button"
                  onMouseDown={() => addChip(r)}
                  className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <span className="truncate font-medium dark:text-white">
                    {r.label}
                  </span>
                  {r.sub && (
                    <span className="ml-auto shrink-0 truncate text-gray-400 text-xs">
                      {r.sub}
                    </span>
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
              className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-100 px-3 py-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            >
              {chip.label}
              {chip.sub && (
                <span className="text-gray-400 text-xs">— {chip.sub}</span>
              )}
              <button
                type="button"
                onClick={() => removeChip(chip.mbid)}
                className="ml-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                aria-label={`Remove ${chip.label}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={handleDiscover}
        disabled={chips.length === 0}
        className="self-start rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Discover
      </button>
    </div>
  );
}

