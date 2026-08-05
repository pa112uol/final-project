import { FOCUS_RING } from "../lib/styles";

export const MOODS = [
  "happy",
  "sad",
  "energetic",
  "chill",
  "melancholic",
  "romantic",
  "focus",
] as const;

export type Mood = (typeof MOODS)[number];

// The "Any" option is always first, then the moods in the order of MOODS.
const OPTIONS: { value: Mood | null; label: string }[] = [
  { value: null, label: "Any" },
  ...MOODS.map((m) => ({ value: m, label: m })),
];

const CHIP = `rounded-full px-4 py-2 text-sm font-semibold border transition-colors ${FOCUS_RING}`;

function chipClass(active: boolean): string {
  return active
    ? `${CHIP} bg-amber border-amber text-bg-base`
    : `${CHIP} bg-fill-subtle border-border-default text-text-secondary hover:bg-fill`;
}

interface MoodPickerProps {
  value: string | null;
  onChange: (mood: string | null) => void;
  // "wrap" suits narrow containers like the sidebar.
  // "grid" the wide search card
  layout?: "grid" | "wrap";
}

export default function MoodPicker({
  value,
  onChange,
  layout = "grid",
}: MoodPickerProps) {
  return (
    <div
      className={
        layout === "wrap" ? "flex flex-wrap gap-2" : "grid grid-cols-4 gap-2"
      }
    >
      {OPTIONS.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.label}
            type="button"
            aria-pressed={active}
            // Re-picking the active mood clears it. "Any" is already null
            onClick={() => onChange(active ? null : option.value)}
            className={`${chipClass(active)} capitalize`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

