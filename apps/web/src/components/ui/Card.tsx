import type { ReactNode } from "react";

type CardProps = {
  title?: string | undefined;
  description?: string | undefined;
  badge?: ReactNode | undefined;
  children: ReactNode;
  className?: string | undefined;
};

/** Contenedor elevado para agrupar contenido relacionado (título + cuerpo). */
export function Card({ title, description, badge, children, className }: CardProps): React.JSX.Element {
  return (
    <div className={["rounded-xl border border-mist bg-white p-6 shadow-sm", className ?? ""].join(" ").trim()}>
      {title !== undefined && title !== "" ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          {badge}
        </div>
      ) : null}
      {description !== undefined && description !== "" ? <p className="mb-4 text-ink/70">{description}</p> : null}
      {children}
    </div>
  );
}
