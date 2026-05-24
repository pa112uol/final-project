const USER_AGENT = "3070-final-project/1.0 (contact@example.com)";
const MB_MIN_INTERVAL_MS = 1_500;

// Promise chain ensures MB requests are fully serialized across all routes.
// Each request waits for the previous fetch + cooldown to finish before firing.
let queue = Promise.resolve();

export function mbFetch(url: string): Promise<Response> {
  const result = queue.then(
    () =>
      new Promise<Response>((resolve, reject) => {
        fetch(url, { headers: { "User-Agent": USER_AGENT } })
          .then(resolve, reject)
          .finally(() => {
            // Hold the queue for the cooldown period after each request
          });
      }),
  );

  // Advance the chain only after cooldown completes (whether fetch succeeded or not)
  queue = result
    .then(
      () => new Promise<void>((r) => setTimeout(r, MB_MIN_INTERVAL_MS)),
      () => new Promise<void>((r) => setTimeout(r, MB_MIN_INTERVAL_MS)),
    )
    .then(() => {});

  return result;
}
