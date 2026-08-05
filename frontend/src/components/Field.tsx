import { useId } from "react";
import type { ReactNode } from "react";
import { SECTION_LABEL } from "../lib/styles";

interface FieldProps {
  label: string;
  hint?: string;
  children: ReactNode;
}

// A form field with a label and optional hint.
// The label is linked to the field for accessibility.
export default function Field({ label, hint, children }: FieldProps) {
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={labelId}>
      <div className="flex items-baseline gap-1.5 mb-3">
        <span id={labelId} className={SECTION_LABEL}>
          {label}
        </span>
        {hint && <span className="text-[13px] text-text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

