import { Link } from "react-router-dom";
import Logo from "./Logo";
import { FOCUS_RING, TOPBAR_HEIGHT } from "../lib/styles";

export default function Navbar() {
  return (
    <nav
      className={`fixed inset-x-0 top-0 z-20 ${TOPBAR_HEIGHT} bg-bg-header border-b border-border-subtle px-4 flex items-center justify-center`}
    >
      <Link
        to="/"
        className={`hover:opacity-80 transition-opacity rounded ${FOCUS_RING}`}
      >
        <Logo size="lg" />
      </Link>
    </nav>
  );
}
