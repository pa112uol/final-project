"use client";

import { useState } from "react";
import dynamic from "next/dynamic";

const TracksList = dynamic(() => import("./TracksList"), { ssr: false });

const MOODS = [
  "happy", "sad", "energetic", "chill",
  "angry", "melancholic", "romantic", "focus",
] as const;

interface Seed {
  id: string; // recording mbid
  t: string;  // title hint
  a: string;  // artist hint
}

function buildUrl(seeds: Seed[], mood: string, novelty: number): string {
  const params = new URLSearchParams();
  for (const s of seeds) {
    params.append("mbid", s.id);
    params.append("title", s.t);
    params.append("artist", s.a);
  }
  if (mood) params.set("mood", mood);
  params.set("novelty", String(novelty));
  return `/api/recommendations?${params.toString()}`;
}

function noveltyLabel(v: number): string {
  if (v < 0.34) return "Popular";
  if (v < 0.67) return "Mixed";
  return "Obscure";
}

export default function TracksListWrapper({ selections }: { selections?: string }) {
  const [mood, setMood] = useState("");
  // novelty controls two states: display (tracks slider position live) and
  // committed (triggers a re-fetch only when the user releases the slider)
  const [noveltyDisplay, setNoveltyDisplay] = useState(0);
  const [noveltyCommitted, setNoveltyCommitted] = useState(0);

  let seeds: Seed[] = [];
  if (selections) {
    try {
      seeds = JSON.parse(selections);
    } catch {}
  }

  if (seeds.length === 0) {
    return <TracksList />;
  }

  const url = buildUrl(seeds, mood, noveltyCommitted);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/50">
        {/* Mood selector */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Mood
          </label>
          <select
            value={mood}
            onChange={(e) => setMood(e.target.value)}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-800 shadow-sm dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
          >
            <option value="">Any</option>
            {MOODS.map((m) => (
              <option key={m} value={m}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Novelty slider */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Novelty
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={noveltyDisplay}
            onChange={(e) => setNoveltyDisplay(Number(e.target.value))}
            onMouseUp={(e) => setNoveltyCommitted(Number((e.target as HTMLInputElement).value))}
            onTouchEnd={(e) => setNoveltyCommitted(Number((e.target as HTMLInputElement).value))}
            className="w-28 accent-zinc-900 dark:accent-zinc-100"
          />
          <span className="w-14 text-xs text-zinc-500 dark:text-zinc-400">
            {noveltyLabel(noveltyDisplay)}
          </span>
        </div>
      </div>

      <TracksList url={url} mode="recommendations" />
    </div>
  );
}
