"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import type { FormEvent } from "react";
import type { Messages } from "@/i18n/messages";
import { Button, Checkbox, Input, Select, Spinner } from "@/components/ui";

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{1,255}$/;

/**
 * Jurisdicciones ofrecidas en el desplegable. El backend (`RegisterIn`)
 * acepta cualquier cadena de hasta 8 caracteres y EXIGE el campo; estas
 * opciones son códigos ISO razonables por defecto y el servidor valida.
 */
const JURISDICTIONS = ["ES", "MX", "AR", "CO", "CL", "PE", "UY", "US"] as const;

type RegisterFormProps = {
  messages: Messages;
};

type ApiResult = {
  error?: unknown;
};

/**
 * Formulario de registro real contra el BFF (`POST /api/auth/register`).
 * Éxito → mensaje "Cuenta creada" + enlace al acceso (cubre tanto el caso
 * con verificación de correo activa como el modo demo sin verificación).
 */
export function RegisterForm({ messages }: RegisterFormProps): React.JSX.Element {
  const register = messages.register;
  const common = messages.common;
  const formRef = useRef<HTMLFormElement>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [jurisdictionError, setJurisdictionError] = useState<string | null>(null);
  const [termsError, setTermsError] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [created, setCreated] = useState(false);
  const [sending, setSending] = useState(false);

  function validate(): boolean {
    let ok = true;
    if (email.trim() === "") {
      setEmailError(common.emailRequired);
      ok = false;
    } else if (!EMAIL_RE.test(email.trim())) {
      setEmailError(common.emailInvalid);
      ok = false;
    } else {
      setEmailError(null);
    }
    if (password === "") {
      setPasswordError(common.passwordRequired);
      ok = false;
    } else if (password.length < 12) {
      setPasswordError(common.passwordMin);
      ok = false;
    } else {
      setPasswordError(null);
    }
    if (jurisdiction === "") {
      setJurisdictionError(register.jurisdictionRequired);
      ok = false;
    } else {
      setJurisdictionError(null);
    }
    if (!acceptTerms) {
      setTermsError(register.termsRequired);
      ok = false;
    } else {
      setTermsError(null);
    }
    return ok;
  }

  async function submit(): Promise<void> {
    setGlobalError(null);
    if (!validate()) return;
    setSending(true);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
          jurisdiction,
          accept_terms: acceptTerms,
        }),
      });
      let data: ApiResult = {};
      try {
        data = (await response.json()) as ApiResult;
      } catch {
        data = {};
      }
      if (!response.ok) {
        // 409 (email ya registrado) y 422/429/5xx llegan aquí con el detalle
        // del servidor (mensajes en español, p. ej. "Ya existe una cuenta…").
        setGlobalError(typeof data.error === "string" && data.error !== "" ? data.error : common.unexpectedError);
        return;
      }
      setCreated(true);
    } catch {
      setGlobalError(common.unexpectedError);
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (sending) return;
    void submit();
  }

  if (created) {
    return (
      <div role="status" className="flex flex-col gap-4 rounded-xl border border-mist bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-ink">{register.successTitle}</h2>
        <p className="text-ink/80">{register.successText}</p>
        <div>
          <Link
            href="/login"
            className="inline-flex items-center justify-center gap-2 rounded-md bg-brand-700 px-5 py-2.5 font-semibold text-white transition hover:bg-brand-800"
          >
            {register.loginLink}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit} aria-busy={sending} noValidate className="flex flex-col gap-5">
      <Input
        label={register.emailLabel}
        name="email"
        type="email"
        autoComplete="email"
        placeholder={register.emailPlaceholder}
        value={email}
        onChange={setEmail}
        required
        disabled={sending}
        error={emailError ?? undefined}
        requiredText={common.fieldRequired}
      />
      <Input
        label={register.passwordLabel}
        name="password"
        type="password"
        autoComplete="new-password"
        placeholder={register.passwordPlaceholder}
        value={password}
        onChange={setPassword}
        minLength={12}
        maxLength={256}
        required
        disabled={sending}
        hint={register.passwordHint}
        error={passwordError ?? undefined}
        requiredText={common.fieldRequired}
      />
      <Select
        label={register.jurisdictionLabel}
        name="jurisdiction"
        value={jurisdiction}
        onChange={setJurisdiction}
        options={JURISDICTIONS.map((code) => ({ value: code, label: code }))}
        placeholder={register.jurisdictionPlaceholder}
        required
        disabled={sending}
        hint={register.jurisdictionHint}
        error={jurisdictionError ?? undefined}
        requiredText={common.fieldRequired}
      />
      <Checkbox
        label={register.termsLabel}
        name="accept_terms"
        checked={acceptTerms}
        onChange={setAcceptTerms}
        required
        disabled={sending}
        hint={register.termsHint}
        error={termsError ?? undefined}
        requiredText={common.fieldRequired}
      />

      {globalError !== null ? (
        <div role="alert" className="flex flex-col gap-3 rounded-md border border-red-800/30 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-800">
            {register.globalError} {globalError}
          </p>
          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={sending}
              onClick={() => formRef.current?.requestSubmit()}
            >
              {common.retry}
            </Button>
          </div>
        </div>
      ) : null}

      <Button type="submit" variant="primary" size="lg" disabled={sending}>
        {sending ? <Spinner label={register.submitting} /> : null}
        {sending ? register.submitting : register.submit}
      </Button>

      <p className="text-sm text-ink/70">
        <small>{register.serverValidationNote}</small>
      </p>
    </form>
  );
}
