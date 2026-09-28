import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-semibold transition focus-visible:outline-brand-800 disabled:cursor-not-allowed disabled:opacity-60";

const VARIANTS: Record<ButtonVariant, string> = {
  // Blanco sobre brand-700 (#0369a1) = 5.9:1; hover brand-800 (#075985) = 7.6:1.
  primary: "bg-brand-700 text-white shadow-sm hover:bg-brand-800",
  secondary: "border border-ink/20 bg-white text-ink hover:bg-mist",
  // Texto brand-800 sobre claro ≈ 7.1:1.
  ghost: "text-brand-800 underline-offset-4 hover:bg-brand-800/10 hover:underline",
  // Blanco sobre red-800 (#991b1b) ≈ 8.3:1.
  danger: "bg-red-800 text-white shadow-sm hover:bg-red-900",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-base",
};

/**
 * Clases del botón como función pura para reutilizarlas en enlaces
 * (`<Link className={buttonClasses("primary", "lg")}>`) sin duplicar variantes.
 */
export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  extra?: string | undefined,
): string {
  return [BASE, VARIANTS[variant], SIZES[size], extra ?? ""].join(" ").trim();
}

type ButtonProps = {
  variant?: ButtonVariant | undefined;
  size?: ButtonSize | undefined;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
    className?: string | undefined;
  };

/** Botón con variantes centralizadas (un solo lugar para primario/secundario/fantasma/peligro). */
export function Button({ variant = "primary", size = "md", type = "button", className, ...rest }: ButtonProps): React.JSX.Element {
  return <button type={type} className={buttonClasses(variant, size, className)} {...rest} />;
}
