"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import type { Messages } from "@/i18n/messages";
import { Button, Input, Spinner } from "@/components/ui";

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{1,255}$/;

type LoginFormProps = {
  messages: Messages;
};

type ApiResult = {
  user?: unknown;
  mfa?: unknown;
  error?: unknown;
};

/**
 * Formulario de acceso real contra el BFF (`POST /api/auth/login`).
 * - Validación por campo con `aria-invalid`/`aria-describedby` (vía `Field`).
 * - Error global con reintento y spinner accesible durante el envío.
 * - La validación del cliente no sustituye la del servidor (nota visible).
 */
export function LoginForm({ messages }: LoginFormProps): React.JSX.Element {
  const login = messages.login;
  const common = messages.common;
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [mfaRequired, setMfaRequired] = useState(false);
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
    return ok;
  }

  async function submit(): Promise<void> {
    setGlobalError(null);
    setMfaRequired(false);
    if (!validate()) return;
    setSending(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      let data: ApiResult = {};
      try {
        data = (await response.json()) as ApiResult;
      } catch {
        data = {};
      }
      if (response.status === 409 && data.mfa === true) {
        setMfaRequired(true);
        return;
      }
      if (!response.ok) {
        setGlobalError(typeof data.error === "string" && data.error !== "" ? data.error : common.unexpectedError);
        return;
      }
      router.push("/panel");
      router.refresh();
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

  function handleRetry(): void {
    formRef.current?.requestSubmit();
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit} aria-busy={sending} noValidate className="flex flex-col gap-5">
      <Input
        label={login.emailLabel}
        name="email"
        type="email"
        autoComplete="email"
        placeholder={login.emailPlaceholder}
        value={email}
        onChange={setEmail}
        required
        disabled={sending}
        error={emailError ?? undefined}
        requiredText={common.fieldRequired}
      />
      <Input
        label={login.passwordLabel}
        name="password"
        type="password"
        autoComplete="current-password"
        placeholder={login.passwordPlaceholder}
        value={password}
        onChange={setPassword}
        minLength={12}
        required
        disabled={sending}
        hint={login.passwordHint}
        error={passwordError ?? undefined}
        requiredText={common.fieldRequired}
      />

      {globalError !== null ? (
        <div role="alert" className="flex flex-col gap-3 rounded-md border border-red-800/30 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-800">
            {login.globalError} {globalError}
          </p>
          <div>
            <Button type="button" variant="secondary" size="sm" onClick={handleRetry} disabled={sending}>
              {common.retry}
            </Button>
          </div>
        </div>
      ) : null}

      {mfaRequired ? (
        <div role="status" className="rounded-md border border-brand-800/30 bg-brand-800/5 p-4">
          <p className="mb-1 text-sm font-semibold text-brand-800">{login.mfaTitle}</p>
          <p className="text-sm text-ink/80">{login.mfaText}</p>
        </div>
      ) : null}

      <Button type="submit" variant="primary" size="lg" disabled={sending}>
        {sending ? <Spinner label={login.submitting} /> : null}
        {sending ? login.submitting : login.submit}
      </Button>

      <p className="text-sm text-ink/70">
        <small>{login.serverValidationNote}</small>
      </p>
    </form>
  );
}
