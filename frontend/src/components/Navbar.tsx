import { Link } from "react-router-dom";

export default function Navbar() {
  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center gap-4">
      <Link
        to="/"
        className="text-white font-semibold hover:text-indigo-400 transition-colors"
      >
        NextTrack
      </Link>
    </nav>
  );
}
