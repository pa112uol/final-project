import TracksListWrapper from "../components/TracksListWrapper";

interface TracksPageProps {
  searchParams: Promise<{ q?: string }>;
}

export default async function TracksPage({ searchParams }: TracksPageProps) {
  const { q } = await searchParams;
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-12">
      <TracksListWrapper selections={q} />
    </main>
  );
}
