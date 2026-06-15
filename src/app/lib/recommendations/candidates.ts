import type { Candidate, PipelineClients } from "./types";
import { ARTISTS_PER_TAG, TOP_ARTISTS_COUNT, TRACKS_PER_ARTIST } from "./constants";

const LB_CONCURRENCY = 5;

class Semaphore {
  private running = 0;
  private queue: Array<() => void> = [];
  constructor(private max: number) {}
  acquire(): Promise<void> {
    if (this.running < this.max) { this.running++; return Promise.resolve(); }
    return new Promise<void>((resolve) => this.queue.push(resolve));
  }
  release(): void {
    this.running--;
    const next = this.queue.shift();
    if (next) { this.running++; next(); }
  }
}

type CandidateClients = Pick<
  PipelineClients,
  "fetchTagArtists" | "fetchArtistTopRecordings" | "resolveArtistMbid"
>;

export async function buildCandidates(
  topTags: [string, number][],
  apiKey: string,
  novelty: number,
  clients: CandidateClients,
): Promise<Candidate[]> {
  // At higher novelty fetch deeper pages of tag.getTopArtists so the long
  // tail of less popular artists enters the pool. Page 1 is always included
  // so relevant artists are never dropped at any novelty level.
  const pagesToFetch = 1 + Math.round(novelty * 2); // 1–3 pages
  const topArtistsCount = Math.round(TOP_ARTISTS_COUNT * (1 + novelty)); // 15–30

  // Phase A: score artists by how many weighted tags they appear in
  const artistScores = new Map<
    string,
    { name: string; tagWeightSum: number; mbid: string }
  >();
  const artistTags = new Map<string, Set<string>>();

  const tagFetchResults = await Promise.allSettled(
    topTags.flatMap(([tag, tagWeight]) =>
      Array.from({ length: pagesToFetch }, (_, pageIdx) =>
        clients
          .fetchTagArtists(tag, pageIdx + 1, ARTISTS_PER_TAG, apiKey)
          .then((artists) => {
            for (let rank = 0; rank < artists.length; rank++) {
              const artist = artists[rank];
              const key = artist.name.toLowerCase();
              if (!artistTags.has(key)) artistTags.set(key, new Set());
              // Guard against crediting the same tag twice if an artist appears
              // on multiple pages of the same tag result
              const tagAlreadyCredited = artistTags.get(key)!.has(tag);
              artistTags.get(key)!.add(tag);
              // Artists ranked higher in tag.getTopArtists are stronger genre representatives.
              // Applying an NDCG style log discount weights rank 1 at 1.0 and rank 30 at 0.20
              const rankDecay = 1 / Math.log2(rank + 2);
              const existing = artistScores.get(key);
              if (existing) {
                if (!tagAlreadyCredited) existing.tagWeightSum += tagWeight * rankDecay;
                if (!existing.mbid && artist.mbid) existing.mbid = artist.mbid;
              } else {
                artistScores.set(key, {
                  name: artist.name,
                  tagWeightSum: tagWeight * rankDecay,
                  mbid: artist.mbid ?? "",
                });
              }
            }
            return { tag, pageIdx };
          }),
      ),
    ),
  );
  for (const result of tagFetchResults) {
    if (result.status === "rejected")
      console.warn("[candidates] fetchTagArtists failed:", result.reason);
  }

  const allScoredArtists = [...artistScores.values()].sort(
    (a, b) => b.tagWeightSum - a.tagWeightSum || a.name.localeCompare(b.name),
  );
  console.log(
    `[candidates] scored artists total:${allScoredArtists.length}, selecting top:${topArtistsCount} (novelty pages:${pagesToFetch})`,
  );

  const topArtists = allScoredArtists.slice(0, topArtistsCount);

  console.log(
    "[candidates] top artists:",
    topArtists
      .map((a) => `${a.name}(${a.tagWeightSum.toFixed(0)})`)
      .join(", "),
  );

  // Resolve missing artist MBIDs via MusicBrainz (serialised by mbFetch queue)
  await Promise.all(
    topArtists
      .filter((a) => !a.mbid)
      .map(async (a) => {
        a.mbid = await clients.resolveArtistMbid(a.name);
        console.log(
          `[candidates] resolved mbid for ${a.name}: ${a.mbid || "not found"}`,
        );
      }),
  );

  // Phase B: fetch top recordings from ListenBrainz: verified MBIDs + listen counts
  const candidates = new Map<string, Candidate>();
  const lbSem = new Semaphore(LB_CONCURRENCY);

  await Promise.allSettled(
    topArtists.map(async (artist) => {
      if (!artist.mbid) return;
      await lbSem.acquire();
      let recordings: Awaited<ReturnType<typeof clients.fetchArtistTopRecordings>>;
      try {
        recordings = await clients.fetchArtistTopRecordings(
          artist.mbid,
          TRACKS_PER_ARTIST,
        );
      } finally {
        lbSem.release();
      }
      const matchedTags = [...(artistTags.get(artist.name.toLowerCase()) ?? [])];
      for (const r of recordings) {
        const key = `${r.title.toLowerCase()}|||${artist.name.toLowerCase()}`;
        candidates.set(key, {
          title: r.title,
          artist: artist.name,
          artistMbid: r.artistMbid,
          mbid: r.mbid,
          durationMs: r.durationMs,
          tagWeightSum: artist.tagWeightSum,
          trackTagScore: 0,
          listenCount: r.listenCount,
          userCount: r.userCount,
          artistListenCount: 0,
          tags: r.tags.length > 0 ? r.tags : matchedTags,
        });
      }
    }),
  );

  const result = [...candidates.values()];
  console.log(`[candidates] total recordings fetched:${result.length}`);
  return result;
}
