import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "info" | "warn" | "danger";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-mist text-ink",
  // Blanco sobre brand-800 (#075985) = 7.6:1.
  info: "bg-brand-800 text-white",
  // amber-900 (#78350f) sobre amber-100 (#fef3c7) ≈ 9:1.
  warn: "border border-amber-800/30 bg-amber-100 text-amber-900",
  // Blanco sobre red-800 (#991b1b) ≈ 8.3:1.
  danger: "bg-red-800 text-white",
};

type BadgeProps = {
  tone?: BadgeTone | undefined;
  mono?: boolean | undefined;
  children: ReactNode;
};

/** Etiqueta pequeña de estado (solo presentación: no sustituye texto explicativo). */
export function Badge({ tone = "neutral", mono = false, children }: BadgeProps): React.JSX.Element {
  return (
    <span
      className={["inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold", TONES[tone], mono ? "font-mono" : ""]
        .join(" ")
        .trim()}
    >
      {children}
    </span>
  );
}
