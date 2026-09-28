type BrandMarkProps = {
  /** Clase CSS adicional (tamaño/color se controlan desde el padre). */
  className?: string;
  /** Título accesible del logotipo. */
  title?: string;
}

/**
 * Marca gráfica propia y provisional de [BRAND_NAME].
 *
 * Diseño original del proyecto (rectángulo redondeado + línea de tendencia
 * ascendente): no reproduce ni deriva de identidades de terceros.
 */
export function BrandMark({ className, title = "[BRAND_NAME]" }: BrandMarkProps): React.JSX.Element {
  return (
    <svg
      className={className}
      viewBox="0 0 48 48"
      role="img"
      aria-label={title}
      focusable="false"
    >
      <rect width="48" height="48" rx="11" fill="var(--color-ink)" />
      <path
        d="M10 33 L20 23 L26 27 L38 14"
        stroke="var(--color-brand-400)"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="38" cy="14" r="3.2" fill="var(--color-brand-400)" />
    </svg>
  );
}
