const DEFAULT_MAX_SEED_TRACKS = 5;

// Read the max seed tracks from the environment variable,
// falling back to the default if not set or invalid
function readMaxSeedTracks(): number {
  const raw = import.meta.env.VITE_MAX_SEED_TRACKS;
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_MAX_SEED_TRACKS;
}

// Shared by the search page (capping how many chips can be added) and the
// results sidebar (showing "n/max" against the seeds already picked).
export const MAX_SEED_TRACKS = readMaxSeedTracks();

