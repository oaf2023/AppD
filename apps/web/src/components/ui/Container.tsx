import type { ReactNode } from "react";

type ContainerProps = {
  children: ReactNode;
  className?: string | undefined;
};

/** Ancho máximo y respiración lateral coherentes en todas las páginas. */
export function Container({ children, className }: ContainerProps): React.JSX.Element {
  return (
    <div className={["mx-auto w-full max-w-5xl px-6", className ?? ""].join(" ").trim()}>{children}</div>
  );
}
