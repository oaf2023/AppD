import { CONTROL_CLASSES } from "./Input";
import { Field } from "./Field";

export type SelectOption = {
  value: string;
  label: string;
};

type SelectProps = {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  placeholder?: string | undefined;
  disabled?: boolean | undefined;
  required?: boolean | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  requiredText?: string | undefined;
};

/** Desplegable con etiqueta, ayuda y error cableados (vía `Field`). */
export function Select({
  label,
  name,
  value,
  onChange,
  options,
  placeholder,
  disabled,
  required,
  error,
  hint,
  requiredText,
}: SelectProps): React.JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required} requiredText={requiredText}>
      <select
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        required={required}
        className={CONTROL_CLASSES}
      >
        {placeholder !== undefined && placeholder !== "" ? (
          <option value="" disabled>
            {placeholder}
          </option>
        ) : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
