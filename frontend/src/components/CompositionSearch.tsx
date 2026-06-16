import { useState, useEffect, useRef } from "react";

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
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const res = await fetch(`/api/search/?q=${encodeURIComponent(query)}`);
      if (!res.ok) return;
      const data = await res.json();
      setResults(data.results || []);
      setOpen(true);
    }, 300);
  }, [query]);

  function addChip(result: SearchResult) {
    if (chips.find((c) => c.mbid === result.mbid)) return;
    setChips([
      ...chips,
      { mbid: result.mbid, title: result.label, artist: result.sub || "" },
    ]);
    setQuery("");
    setOpen(false);
  }

  function removeChip(mbid: string) {
    setChips(chips.filter((c) => c.mbid !== mbid));
  }

  function discover() {
    if (chips.length > 0) onDiscover(chips);
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for a track..."
          className="w-full bg-gray-800 text-white rounded-lg px-4 py-3 outline-none focus:ring-2 focus:ring-indigo-500"
        />
        {open && results.length > 0 && (
          <ul className="absolute z-10 w-full bg-gray-800 rounded-lg mt-1 shadow-xl max-h-64 overflow-y-auto">
            {results.map((r) => (
              <li key={r.mbid}>
                <button
                  onClick={() => addChip(r)}
                  className="w-full text-left px-4 py-2 hover:bg-gray-700 transition-colors"
                >
                  <span className="font-medium">{r.label}</span>
                  {r.sub && (
                    <span className="text-gray-400 text-sm ml-2">{r.sub}</span>
                  )}
                </button>
              </li>
            ))}
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
              {c.title}
              {c.artist && (
                <span className="text-indigo-300 font-normal">· {c.artist}</span>
              )}
              <button
                onClick={() => removeChip(c.mbid)}
                className="ml-1 hover:text-red-300"
              >
                x
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
