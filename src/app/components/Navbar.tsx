import Link from "next/link";

export default function Navbar() {
  return (
    <nav className="flex h-12 items-center border-b border-[#1a1a1a] px-6">
      <Link
        href="/"
        className="flex items-center gap-2 text-sm font-medium text-white hover:opacity-80 transition-opacity"
      >
        <span className="text-base font-bold">🎧</span>
        <span className="h-4 w-px bg-[#333]" />
        <span className="font-mono text-[#888]">nexttrack</span>
      </Link>
    </nav>
  );
}

