import CompositionSearch from "./components/CompositionSearch";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-[#333] bg-[#111] p-8 shadow-2xl">
          <div className="flex flex-col gap-6">
            <div>
              <h1 className="text-xl font-semibold text-white">
                Find your next track
              </h1>
              <p className="mt-1 text-sm text-[#888]">
                Search an artist or song to discover something new.
              </p>
            </div>
            <CompositionSearch />
          </div>
        </div>
      </div>
    </main>
  );
}

