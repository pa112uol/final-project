import type { CSSProperties } from "react";
import { FOCUS_RING } from "../lib/styles";

interface NoveltySliderProps {
  value: number;
  onChange: (value: number) => void;
  onCommit?: (value: number) => void;
}

// The slider stores 0–1 but reads out as 0–100 everywhere it is shown.
export function noveltyPct(value: number): number {
  return Math.round(value * 100);
}

export default function NoveltySlider({
  value,
  onChange,
  onCommit,
}: NoveltySliderProps) {
  const pct = noveltyPct(value);

  return (
    <div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={
          onCommit
            ? (e) => onCommit(Number((e.target as HTMLInputElement).value))
            : undefined
        }
        onTouchEnd={
          onCommit
            ? (e) => onCommit(Number((e.target as HTMLInputElement).value))
            : undefined
        }
        aria-label={`Novelty: ${pct} out of 100`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        style={{ "--pct": `${pct}%` } as CSSProperties}
        className={`range-amber rounded ${FOCUS_RING}`}
      />
      <div
        className="flex justify-between text-xs text-text-muted mt-2"
        aria-hidden="true"
      >
        <span>Popular</span>
        <span>Obscure</span>
      </div>
    </div>
  );
}

