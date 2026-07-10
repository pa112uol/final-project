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

interface MoodPickerProps {
  value: string | null;
  onChange: (mood: string | null) => void;
}

export default function MoodPicker({ value, onChange }: MoodPickerProps) {
  return (
    <div className="grid grid-cols-4 gap-2">
      <button
        onClick={() => onChange(null)}
        className={`px-3 py-1.5 rounded-full text-sm transition-colors ${FOCUS_RING} ${
          value === null
            ? "bg-amber text-bg-base font-semibold"
            : "border border-border-default text-text-secondary hover:bg-bg-raised"
        }`}
      >
        Any
      </button>
      {MOODS.map((m) => (
        <button
          key={m}
          onClick={() => onChange(m === value ? null : m)}
          className={`px-3 py-1.5 rounded-full text-sm capitalize transition-colors ${FOCUS_RING} ${
            value === m
              ? "bg-amber text-bg-base font-semibold"
              : "border border-border-default text-text-secondary hover:bg-bg-raised"
          }`}
        >
          {m}
        </button>
      ))}
    </div>
  );
}
