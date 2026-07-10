import { FOCUS_RING } from "../lib/styles";

interface NoveltySliderProps {
  value: number;
  onChange: (value: number) => void;
  onCommit?: (value: number) => void;
}

export default function NoveltySlider({ value, onChange, onCommit }: NoveltySliderProps) {
  const pct = Math.round(value * 100);

  return (
    <div>
      <p className="text-sm text-text-secondary mb-1">
        Novelty:{" "}
        <span className="font-semibold text-text-primary">{pct}</span>
        <span className="text-text-muted"> / 100</span>
      </p>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={onCommit ? (e) => onCommit(Number((e.target as HTMLInputElement).value)) : undefined}
        onTouchEnd={onCommit ? (e) => onCommit(Number((e.target as HTMLInputElement).value)) : undefined}
        aria-label={`Novelty: ${pct} out of 100`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className={`w-full accent-blue rounded ${FOCUS_RING}`}
      />
      <div
        className="flex justify-between text-xs text-text-muted mt-1"
        aria-hidden="true"
      >
        <span>Popular</span>
        <span>Obscure</span>
      </div>
    </div>
  );
}
