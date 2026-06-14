"use client";

import { useState } from "react";
import dynamic from "next/dynamic";

function TracksListSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <p className="animate-pulse text-sm text-slate-500">Analysing your taste…</p>
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-24 animate-pulse rounded-2xl border border-white/5 bg-white/[0.03]" />
      ))}
    </div>
  );
}

const TracksList = dynamic(() => import("./TracksList"), {
  ssr: false,
  loading: TracksListSkeleton,
});

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
  const [refreshKey, setRefreshKey] = useState(0);
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
    return (
      <TracksList
        key={refreshKey}
        onRefresh={() => setRefreshKey((k) => k + 1)}
      />
    );
  }

  const url = buildUrl(seeds, mood, noveltyCommitted);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
        {/* Mood selector */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Mood
          </label>
          <select
            value={mood}
            onChange={(e) => setMood(e.target.value)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-200 outline-none transition focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20"
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
          <label className="text-xs font-medium uppercase tracking-wide text-slate-500">
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
            onKeyUp={(e) => setNoveltyCommitted(Number((e.target as HTMLInputElement).value))}
            className="w-28 accent-violet-500"
          />
          <span className="w-14 text-xs text-slate-500">
            {noveltyLabel(noveltyDisplay)}
          </span>
        </div>
      </div>

      <TracksList
        key={`${url}-${refreshKey}`}
        url={url}
        mode="recommendations"
        onRefresh={() => setRefreshKey((k) => k + 1)}
      />
    </div>
  );
}
