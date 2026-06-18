import { useNavigate } from "react-router-dom";
import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import CompositionSearch from "./components/CompositionSearch";
import TracksListWrapper from "./components/TracksListWrapper";

interface Seed {
  mbid: string;
  title: string;
  artist: string;
}

function SearchPage() {
  const navigate = useNavigate();

  function handleDiscover(seeds: Seed[]) {
    const params = new URLSearchParams();
    seeds.forEach((s) => {
      params.append("mbid", s.mbid);
      params.append("title", s.title);
      params.append("artist", s.artist);
    });
    navigate(`/results?${params.toString()}`);
  }

  return (
    <div className="rounded-2xl bg-bg-surface p-8 shadow-xl">
      <h1 className="text-3xl font-bold mb-2 text-text-primary">NextTrack</h1>
      <p className="text-text-secondary mb-8">
        Search for a track to discover similar music.
      </p>
      <CompositionSearch onDiscover={handleDiscover} />
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-bg-base text-text-primary">
      <Navbar />
      <main className="max-w-3xl mx-auto px-4 py-12">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/results" element={<TracksListWrapper />} />
        </Routes>
      </main>
    </div>
  );
}
