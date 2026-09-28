import { Field } from "./Field";

export const CONTROL_CLASSES =
  "w-full rounded-md border border-ink/25 bg-white px-3 py-2 text-ink shadow-sm transition placeholder:text-ink/55 hover:border-ink/40 focus:border-brand-800 disabled:cursor-not-allowed disabled:bg-mist/60 disabled:text-ink/50 aria-[invalid=true]:border-red-700";

type InputProps = {
  label: string;
  name: string;
  type: "email" | "password" | "text";
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string | undefined;
  placeholder?: string | undefined;
  minLength?: number | undefined;
  maxLength?: number | undefined;
  disabled?: boolean | undefined;
  required?: boolean | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  requiredText?: string | undefined;
};

/** Campo de texto controlado con etiqueta, ayuda y error cableados (vía `Field`). */
export function Input({
  label,
  name,
  type,
  value,
  onChange,
  autoComplete,
  placeholder,
  minLength,
  maxLength,
  disabled,
  required,
  error,
  hint,
  requiredText,
}: InputProps): React.JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required} requiredText={requiredText}>
      <input
        name={name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        minLength={minLength}
        maxLength={maxLength}
        disabled={disabled}
        required={required}
        className={CONTROL_CLASSES}
      />
    </Field>
  );
}
