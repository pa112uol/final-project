import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Shuffle } from "lucide-react";
import Navbar from "./components/Navbar";
import Logo from "./components/Logo";
import CompositionSearch from "./components/CompositionSearch";
import TracksListWrapper from "./components/TracksListWrapper";
import TracksList from "./components/TracksList";
import PageHeader from "./components/PageHeader";
import { TOPBAR_PAD } from "./lib/styles";
import type { Seed } from "./lib/types";

function SearchPage() {
  const navigate = useNavigate();

  function handleDiscover(seeds: Seed[], mood: string | null, novelty: number) {
    const params = new URLSearchParams();
    seeds.forEach((s) => {
      params.append("mbid", s.mbid);
      params.append("title", s.title);
      params.append("artist", s.artist);
    });
    if (mood) params.set("mood", mood);
    params.set("novelty", String(novelty));
    navigate(`/results?${params.toString()}`);
  }

  return (
    <div className="min-h-screen bg-bg-base text-text-primary flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl">
        <h1 className="flex justify-center mb-8">
          <Logo size="hero" />
        </h1>
        <div className="rounded-2xl bg-bg-surface p-10 shadow-xl">
          <CompositionSearch
            onDiscover={handleDiscover}
            onRandom={() => navigate("/random")}
          />
        </div>
      </div>
    </div>
  );
}

function ResultsPage() {
  return (
    <div className={`min-h-screen bg-bg-base text-text-primary ${TOPBAR_PAD}`}>
      <Navbar />
      <TracksListWrapper />
    </div>
  );
}

function RandomPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <div className={`min-h-screen bg-bg-base text-text-primary ${TOPBAR_PAD}`}>
      <Navbar />
      <main className="max-w-[760px] mx-auto px-5 py-6 lg:px-10 lg:py-8">
        <PageHeader title="Random picks" />
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="w-full bg-amber hover:bg-amber-dark text-bg-base font-semibold rounded-lg px-4 py-3 transition-colors mb-8"
        >
          <Shuffle className="inline-block mr-2 w-4 h-4" /> Shuffle
        </button>
        <TracksList key={refreshKey} url="/api/random/" />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<SearchPage />} />
      <Route path="/results" element={<ResultsPage />} />
      <Route path="/random" element={<RandomPage />} />
    </Routes>
  );
}
