import { Link } from "react-router-dom";
import Logo from "./Logo";
import { FOCUS_RING } from "../lib/styles";

export default function Navbar() {
  return (
    <nav className="bg-bg-surface border-b border-border-subtle px-4 py-3 flex items-center justify-center">
      <Link
        to="/"
        className={`hover:opacity-80 transition-opacity rounded ${FOCUS_RING}`}
      >
        <Logo size="lg" />
      </Link>
    </nav>
  );
}
