import { Field } from "./Field";

type CheckboxProps = {
  label: string;
  name: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean | undefined;
  required?: boolean | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  requiredText?: string | undefined;
};

/** Casilla de verificación con etiqueta, ayuda y error cableados (vía `Field`). */
export function Checkbox({
  label,
  name,
  checked,
  onChange,
  disabled,
  required,
  error,
  hint,
  requiredText,
}: CheckboxProps): React.JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required} requiredText={requiredText}>
      <input
        name={name}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        required={required}
        className="h-5 w-5 shrink-0 rounded border-ink/25 accent-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
      />
    </Field>
  );
}
