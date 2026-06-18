import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import TracksList from "./TracksList";
import { FOCUS_RING } from "../lib/styles";

const MOODS = [
  "happy",
  "sad",
  "energetic",
  "chill",
  "angry",
  "melancholic",
  "romantic",
  "focus",
] as const;


export default function TracksListWrapper() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [refreshKey, setRefreshKey] = useState(0);

  const mbids = searchParams.getAll("mbid");
  const titles = searchParams.getAll("title");
  const artists = searchParams.getAll("artist");
  const seeds = mbids.map((mbid, i) => ({
    mbid,
    title: titles[i] || "",
    artist: artists[i] || "",
  }));

  const mood = searchParams.get("mood");
  const novelty = Number(searchParams.get("novelty") ?? 0);
  const [noveltyDisplay, setNoveltyDisplay] = useState(novelty);

  function setMood(m: string | null) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (m) next.set("mood", m);
        else next.delete("mood");
        return next;
      },
      { replace: true },
    );
  }

  function commitNovelty(value: number) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("novelty", String(value));
        return next;
      },
      { replace: true },
    );
  }

  const apiParams = new URLSearchParams();
  seeds.forEach((s) => {
    apiParams.append("mbid", s.mbid);
    apiParams.append("title", s.title);
    apiParams.append("artist", s.artist);
  });
  if (mood) apiParams.set("mood", mood);
  apiParams.set("novelty", String(novelty));
  const apiUrl = `/api/recommendations/?${apiParams.toString()}`;

  const noveltyPct = Math.round(noveltyDisplay * 100);

  return (
    <div className="space-y-6">
      <div className="bg-bg-surface rounded-xl p-4 space-y-4">
        <div>
          <p className="text-sm text-text-secondary mb-2">Mood</p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setMood(null)}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${FOCUS_RING} ${
                mood === null
                  ? "bg-amber text-bg-base font-semibold"
                  : "border border-border-default text-text-secondary hover:bg-bg-raised"
              }`}
            >
              {mood === null && <span aria-hidden="true">✓ </span>}Any
            </button>
            {MOODS.map((m) => (
              <button
                key={m}
                onClick={() => setMood(m === mood ? null : m)}
                className={`px-3 py-1 rounded-full text-sm capitalize transition-colors ${FOCUS_RING} ${
                  mood === m
                    ? "bg-amber text-bg-base font-semibold"
                    : "border border-border-default text-text-secondary hover:bg-bg-raised"
                }`}
              >
                {mood === m && <span aria-hidden="true">✓ </span>}{m}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-sm text-text-secondary mb-1">
            Novelty:{" "}
            <span className="font-semibold text-text-primary">{noveltyPct}</span>
            <span className="text-text-muted"> / 100</span>
          </p>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={noveltyDisplay}
            onChange={(e) => setNoveltyDisplay(Number(e.target.value))}
            onMouseUp={(e) =>
              commitNovelty(Number((e.target as HTMLInputElement).value))
            }
            onTouchEnd={(e) =>
              commitNovelty(Number((e.target as HTMLInputElement).value))
            }
            aria-label={`Novelty: ${noveltyPct} out of 100`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={noveltyPct}
            className={`w-full accent-blue rounded ${FOCUS_RING}`}
          />
          <div
            className="flex justify-between text-xs text-text-muted mt-1"
            aria-hidden="true"
          >
            <span>Popular</span>
            <span>Obscure</span>
          </div>
        </div>
      </div>

      <TracksList
        key={`${apiUrl}-${refreshKey}`}
        url={apiUrl}
        onRefresh={() => setRefreshKey((k) => k + 1)}
      />
    </div>
  );
}
