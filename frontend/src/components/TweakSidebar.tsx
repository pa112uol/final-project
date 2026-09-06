import { SlidersHorizontal } from "lucide-react";
import Field from "./Field";
import MoodPicker from "./MoodPicker";
import NoveltySlider, { noveltyPct } from "./NoveltySlider";
import SeedList from "./SeedList";
import { SIDEBAR_FIXED } from "../lib/styles";
import type { Seed } from "../lib/types";

interface TweakSidebarProps {
  seeds: Seed[];
  mood: string | null;
  onMoodChange: (mood: string | null) => void;
  novelty: number;
  onNoveltyChange: (value: number) => void;
  onNoveltyCommit: (value: number) => void;
}

export default function TweakSidebar({
  seeds,
  mood,
  onMoodChange,
  novelty,
  onNoveltyChange,
  onNoveltyCommit,
}: TweakSidebarProps) {
  return (
    <aside
      aria-label="Recommendation controls"
      className={`bg-bg-base border-b border-border-subtle px-6 py-7 space-y-7 ${SIDEBAR_FIXED} lg:overflow-y-auto lg:border-b-0 lg:border-r`}
    >
      <h2 className="flex items-center gap-2.5 text-[17px] font-bold text-text-primary">
        <SlidersHorizontal className="w-[18px] h-[18px] text-amber" />
        Tweak
      </h2>

      <Field label="Mood">
        <MoodPicker value={mood} onChange={onMoodChange} layout="wrap" />
      </Field>

      <Field label="Novelty" hint={`${noveltyPct(novelty)} / 100`}>
        <NoveltySlider
          value={novelty}
          onChange={onNoveltyChange}
          onCommit={onNoveltyCommit}
        />
      </Field>

      <SeedList seeds={seeds} />
    </aside>
  );
}
