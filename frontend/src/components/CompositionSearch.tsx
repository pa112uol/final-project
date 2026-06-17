import { useState, useEffect, useRef, useCallback } from "react";

interface SearchResult {
  type: "track";
  mbid: string;
  label: string;
  sub?: string;
}

interface Seed {
  mbid: string;
  title: string;
  artist: string;
}

interface CompositionSearchProps {
  onDiscover: (seeds: Seed[]) => void;
}

export default function CompositionSearch({
  onDiscover,
}: CompositionSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [chips, setChips] = useState<Seed[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      setLoading(false);
      setActiveIndex(-1);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
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
  }, [query]);

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
      if (chips.find((c) => c.mbid === result.mbid)) {
        setQuery("");
        setOpen(false);
        setActiveIndex(-1);
        inputRef.current?.focus();
        return;
      }
      setChips((prev) => [
        ...prev,
        { mbid: result.mbid, title: result.label, artist: result.sub || "" },
      ]);
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
    if (chips.length > 0) onDiscover(chips);
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

  const showDropdown = open && !loading && query.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="relative" ref={containerRef}>
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              if (results.length > 0) setOpen(true);
            }}
            placeholder="Search for a track or artist - track..."
            autoComplete="off"
            spellCheck={false}
            className="w-full bg-gray-800 text-white rounded-lg px-4 py-3 pr-10 outline-none focus:ring-2 focus:ring-indigo-500"
          />
          {loading && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2">
              <svg
                className="animate-spin h-4 w-4 text-indigo-400"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
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
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
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
            className="absolute z-10 w-full bg-gray-800 rounded-lg mt-1 shadow-xl max-h-64 overflow-y-auto"
            role="listbox"
          >
            {results.length === 0 ? (
              <li className="px-4 py-3 text-gray-500 text-sm">
                No results for "{query}"
              </li>
            ) : (
              results.map((r, i) => {
                const isActive = i === activeIndex;
                const isAdded = chips.some((c) => c.mbid === r.mbid);
                return (
                  <li key={r.mbid} role="option" aria-selected={isActive}>
                    <button
                      onMouseDown={(e) => {
                        e.preventDefault();
                        addChip(r);
                      }}
                      onMouseEnter={() => setActiveIndex(i)}
                      className={`w-full text-left px-4 py-2.5 transition-colors flex items-center justify-between gap-2 ${
                        isActive ? "bg-indigo-700" : "hover:bg-gray-700"
                      }`}
                    >
                      <span className="flex flex-col min-w-0">
                        <span className="font-medium truncate">{r.label}</span>
                        {r.sub && (
                          <span className="text-gray-400 text-sm truncate">
                            {r.sub}
                          </span>
                        )}
                      </span>
                      {isAdded && (
                        <span className="shrink-0 text-xs text-indigo-300">
                          added
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
        <div className="flex flex-wrap gap-2">
          {chips.map((c) => (
            <span
              key={c.mbid}
              className="inline-flex items-center gap-1 bg-indigo-700 text-white rounded-full px-3 py-1 text-sm"
            >
              <span className="font-medium">{c.title}</span>
              {c.artist && (
                <span className="text-indigo-300 font-normal">
                  · {c.artist}
                </span>
              )}
              <button
                onClick={() => removeChip(c.mbid)}
                className="ml-1 hover:text-red-300 transition-colors leading-none"
                aria-label={`Remove ${c.title}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <button
        onClick={discover}
        disabled={chips.length === 0}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-lg px-4 py-3 transition-colors"
      >
        Discover
      </button>
    </div>
  );
}
