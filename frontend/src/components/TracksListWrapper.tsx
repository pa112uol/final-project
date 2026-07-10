import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import TracksList from "./TracksList";
import NoveltySlider from "./NoveltySlider";
import MoodPicker from "./MoodPicker";

export default function TracksListWrapper() {
  const [searchParams, setSearchParams] = useSearchParams();

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
      <div className="bg-bg-surface rounded-xl p-4 space-y-4">
        <div>
          <p className="text-sm text-text-secondary mb-2">Mood</p>
          <MoodPicker value={mood} onChange={setMood} />
        </div>

        <NoveltySlider
          value={noveltyDisplay}
          onChange={setNoveltyDisplay}
          onCommit={commitNovelty}
        />
      </div>

      <TracksList key={apiUrl} url={apiUrl} />
    </div>
  );
}
