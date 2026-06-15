// MusicBrainz requires a meaningful User-Agent: App/Version (contact)
// See: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
const MB_BASE = "https://musicbrainz.org/ws/2";
const USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)";
const MB_MIN_INTERVAL_MS = 1_500;

// Promise chain ensures MB requests are fully serialized across all routes.
// Each request waits for the previous fetch + cooldown to finish before firing.
let queue = Promise.resolve();

export function mbFetch(url: string): Promise<Response> {
  const result = queue.then(
    () =>
      new Promise<Response>((resolve, reject) => {
        fetch(url, { headers: { "User-Agent": USER_AGENT } }).then(
          resolve,
          reject,
        );
      }),
  );

  // Advance the chain only after cooldown completes, whether fetch succeeded or not
  queue = result
    .then(
      () => new Promise<void>((r) => setTimeout(r, MB_MIN_INTERVAL_MS)),
      () => new Promise<void>((r) => setTimeout(r, MB_MIN_INTERVAL_MS)),
    )
    .then(() => {});

  return result;
}

export async function resolveArtistMbid(name: string): Promise<string> {
  try {
    const query = `artist:"${name.replace(/"/g, "")}"`;
    const res = await mbFetch(
      `${MB_BASE}/artist?query=${encodeURIComponent(query)}&limit=1&fmt=json`,
    );
    if (!res.ok) return "";
    const data = (await res.json()) as { artists?: { id: string; score: number }[] };
    const top = data.artists?.[0];
    if (!top || top.score < 85) return "";
    return top.id;
  } catch {
    return "";
  }
}

