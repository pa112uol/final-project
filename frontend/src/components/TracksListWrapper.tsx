import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import TracksList from "./TracksList";

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

  return (
    <div className="space-y-6">
      <div className="bg-gray-900 rounded-xl p-4 space-y-4">
        <div>
          <p className="text-sm text-gray-400 mb-2">Mood</p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setMood(null)}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${
                mood === null
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-800 text-gray-300 hover:bg-gray-700"
              }`}
            >
              Any
            </button>
            {MOODS.map((m) => (
              <button
                key={m}
                onClick={() => setMood(m === mood ? null : m)}
                className={`px-3 py-1 rounded-full text-sm capitalize transition-colors ${
                  mood === m
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-sm text-gray-400 mb-1">
            Novelty:{" "}
            {noveltyDisplay === 0
              ? "Popular"
              : noveltyDisplay === 1
                ? "Obscure"
                : noveltyDisplay.toFixed(1)}
          </p>
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={noveltyDisplay}
            onChange={(e) => setNoveltyDisplay(Number(e.target.value))}
            onMouseUp={(e) =>
              commitNovelty(Number((e.target as HTMLInputElement).value))
            }
            onTouchEnd={(e) =>
              commitNovelty(Number((e.target as HTMLInputElement).value))
            }
            className="w-full accent-indigo-500"
          />
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
