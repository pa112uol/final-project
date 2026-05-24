import TracksListWrapper from "./components/TracksListWrapper";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-12">
      <TracksListWrapper />
    </main>
  );
}
