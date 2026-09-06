import CoverArt from "./CoverArt";
import Field from "./Field";
import { MAX_SEED_TRACKS } from "../lib/seedTracks";
import type { Seed } from "../lib/types";

interface SeedListProps {
  seeds: Seed[];
}

// Read-only recap of the tracks currently seeding these recommendations.
export default function SeedList({ seeds }: SeedListProps) {
  if (seeds.length === 0) return null;

  return (
    <Field label="Selected tracks" hint={`${seeds.length}/${MAX_SEED_TRACKS}`}>
      <ul className="space-y-2">
        {seeds.map((s) => (
          <li
            key={s.mbid}
            className="flex items-center gap-2.5 bg-bg-raised border border-border-default rounded-lg px-2.5 py-2"
          >
            <CoverArt mbid={s.mbid} className="w-9 h-9 rounded-md" />
            <span className="min-w-0 flex flex-col leading-tight">
              <span className="font-medium text-text-primary truncate text-sm">
                {s.title}
              </span>
              {s.artist && (
                <span className="text-text-secondary text-xs truncate">
                  {s.artist}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </Field>
  );
}

