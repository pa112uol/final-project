import CompositionSearch from "./components/CompositionSearch";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-12">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold dark:text-white">Discover Music</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Search for artists or tracks you enjoy, then let us find something new for you.
        </p>
      </div>
      <CompositionSearch />
    </main>
  );
}
