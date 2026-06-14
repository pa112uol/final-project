import Link from "next/link";
import TracksListWrapper from "../components/TracksListWrapper";

interface TracksPageProps {
  searchParams: Promise<{ q?: string }>;
}

export default async function TracksPage({ searchParams }: TracksPageProps) {
  const { q } = await searchParams;
  return (
    <main className="min-h-screen">
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-12">
        <Link
          href="/"
          className="inline-flex w-fit items-center gap-2 text-sm text-slate-500 transition-colors hover:text-slate-300"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to search
        </Link>
        <TracksListWrapper selections={q} />
      </div>
    </main>
  );
}
