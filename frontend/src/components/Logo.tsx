import { Activity } from "lucide-react";

type LogoSize = "sm" | "md" | "lg" | "hero";

const sizes: Record<LogoSize, { icon: number; textClass: string; gapClass: string; strokeWidth: number }> = {
  sm:   { icon: 16, textClass: "text-[13px] tracking-normal",      gapClass: "gap-1.5", strokeWidth: 2.5 },
  md:   { icon: 20, textClass: "text-base tracking-normal",        gapClass: "gap-2",   strokeWidth: 2.2 },
  lg:   { icon: 26, textClass: "text-[22px] tracking-[-0.02em]",   gapClass: "gap-2.5", strokeWidth: 2.2 },
  hero: { icon: 44, textClass: "text-[36px] tracking-[-0.02em]",   gapClass: "gap-3.5", strokeWidth: 2.2 },
};

interface LogoProps {
  size?: LogoSize;
}

export default function Logo({ size = "lg" }: LogoProps) {
  const s = sizes[size];
  return (
    <div className={`flex items-center ${s.gapClass} leading-none whitespace-nowrap`}>
      <Activity
        size={s.icon}
        strokeWidth={s.strokeWidth}
        className="text-amber"
      />
      <span className={`font-outfit font-extrabold ${s.textClass} text-text-primary`}>
        NextTrack
      </span>
    </div>
  );
}
