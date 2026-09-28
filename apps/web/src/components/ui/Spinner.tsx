type SpinnerProps = {
  /** Texto anunciado por lectores de pantalla (p. ej. "Entrando…"). */
  label: string;
  /** Muestra el texto en visible además de anunciarlo. */
  visibleLabel?: boolean | undefined;
  className?: string | undefined;
};

/** Indicador de carga accesible (`role="status"` anuncia el texto automáticamente). */
export function Spinner({ label, visibleLabel = false, className }: SpinnerProps): React.JSX.Element {
  return (
    <span role="status" className={["inline-flex items-center gap-2", className ?? ""].join(" ").trim()}>
      <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      <span className={visibleLabel ? "" : "sr-only"}>{label}</span>
    </span>
  );
}
