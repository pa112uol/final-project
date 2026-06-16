import { Routes, Route, useNavigate } from "react-router-dom";
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
    <div className="rounded-2xl bg-gray-900 p-8 shadow-xl">
      <h1 className="text-3xl font-bold mb-2">NextTrack</h1>
      <p className="text-gray-400 mb-8">
        Search for a track to discover similar music.
      </p>
      <CompositionSearch onDiscover={handleDiscover} />
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
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
