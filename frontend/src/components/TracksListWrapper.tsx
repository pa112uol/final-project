import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import TracksList from "./TracksList";
import TweakSidebar from "./TweakSidebar";
import PageHeader from "./PageHeader";
import { SIDEBAR_PAD } from "../lib/styles";

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
    <div className={SIDEBAR_PAD}>
      <TweakSidebar
        seeds={seeds}
        mood={mood}
        onMoodChange={setMood}
        novelty={noveltyDisplay}
        onNoveltyChange={setNoveltyDisplay}
        onNoveltyCommit={commitNovelty}
      />

      <main className="px-5 py-6 lg:px-10 lg:py-8">
        <div className="max-w-[760px] mx-auto">
          <PageHeader title="Similar tracks" />
          <TracksList
            key={apiUrl}
            url={apiUrl}
            novelty={novelty}
            resolveRecordings
          />
        </div>
      </main>
    </div>
  );
}

