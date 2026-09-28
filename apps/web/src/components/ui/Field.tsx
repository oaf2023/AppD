import { cloneElement, isValidElement, useId } from "react";
import type { ReactElement, ReactNode } from "react";

type FieldProps = {
  /** Texto visible de la etiqueta. */
  label: string;
  /** Error de validación del campo (activa `aria-invalid` y `aria-describedby`). */
  error?: string | undefined;
  /** Ayuda visible bajo el control. */
  hint?: string | undefined;
  /** Marca el campo como obligatorio (`*` + texto solo-lector). */
  required?: boolean | undefined;
  /** Texto solo-lector que acompaña al `*` (p. ej. "Campo obligatorio"). */
  requiredText?: string | undefined;
  children: ReactNode;
};

type InjectedControlProps = {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby"?: string | undefined;
};

/**
 * Agrupa etiqueta + control + ayuda/error con el cableado ARIA correcto.
 *
 * Genera un `id` estable y lo inyecta en el control hijo junto con
 * `aria-invalid` y `aria-describedby` (apunta a ayuda y/o error cuando
 * existen). Un único lugar para el patrón label/hint/error de la app.
 */
export function Field({ label, error, hint, required, requiredText, children }: FieldProps): React.JSX.Element {
  const rawId = useId();
  const inputId = `campo-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const hintId = `${inputId}-ayuda`;
  const errorId = `${inputId}-error`;
  const hasError = error !== undefined && error !== "";
  const describedBy = hasError ? (hint ? `${hintId} ${errorId}` : errorId) : hint ? hintId : undefined;

  let control = children;
  if (isValidElement(children)) {
    const injected: InjectedControlProps = {
      id: inputId,
      "aria-invalid": hasError,
      ...(describedBy === undefined ? {} : { "aria-describedby": describedBy }),
    };
    control = cloneElement(children as ReactElement<InjectedControlProps>, injected);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-sm font-semibold text-ink">
        {label}
        {required === true ? (
          <>
            {" "}
            <span aria-hidden="true" className="text-brand-800">
              *
            </span>
            {requiredText ? <span className="sr-only">({requiredText})</span> : null}
          </>
        ) : null}
      </label>
      {control}
      {hint ? (
        <p id={hintId} className="text-sm text-ink/70">
          {hint}
        </p>
      ) : null}
      {hasError ? (
        <p id={errorId} className="text-sm font-medium text-red-800">
          {error}
        </p>
      ) : null}
    </div>
  );
}
