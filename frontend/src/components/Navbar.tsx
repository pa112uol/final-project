import { Link } from "react-router-dom";
import { FOCUS_RING } from "../lib/styles";

export default function Navbar() {
  return (
    <nav className="bg-bg-surface border-b border-border-subtle px-4 py-3 flex items-center">
      <Link
        to="/"
        className={`text-text-primary font-semibold hover:text-amber transition-colors rounded ${FOCUS_RING}`}
      >
        NextTrack
      </Link>
    </nav>
  );
}
