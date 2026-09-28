"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import type { Messages } from "@/i18n/messages";

type Status = "idle" | "sending" | "mock-ok";

type LoginFormProps = {
  messages: Messages["login"];
};

/**
 * Formulario de acceso en estado MOCK (Fase 1 — foundation).
 *
 * - NO realiza ninguna llamada de red: el `submit` solo simula un envío local
 *   para ejercitar los estados `loading`/`success` de la UI.
 * - La validación aquí es solo de cliente (`required`, `type="email"`,
 *   `minLength`); la validación del servidor seguirá siendo obligatoria
 *   cuando exista el backend.
 */
export function LoginForm({ messages }: LoginFormProps): React.JSX.Element {
  const [status, setStatus] = useState<Status>("idle");

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (status === "sending") return;
    setStatus("sending");
    // Simulación local del retardo de red; no hay fetch ni backend.
    window.setTimeout(() => setStatus("mock-ok"), 600);
  }

  const isSending = status === "sending";

  return (
    <form onSubmit={handleSubmit} noValidate={false} aria-busy={isSending}>
      <p role="note">{messages.mockNotice}</p>

      <div>
        <label htmlFor="login-email">{messages.emailLabel}</label>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          placeholder={messages.emailPlaceholder}
          disabled={isSending}
        />
      </div>

      <div>
        <label htmlFor="login-password">{messages.passwordLabel}</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          minLength={8}
          placeholder={messages.passwordPlaceholder}
          disabled={isSending}
        />
      </div>

      <button type="submit" disabled={isSending}>
        {isSending ? messages.submitting : messages.submit}
      </button>

      {status === "mock-ok" ? (
        <p role="status">{messages.mockResult}</p>
      ) : null}

      <p>
        <small>{messages.serverValidationNote}</small>
      </p>
    </form>
  );
}
