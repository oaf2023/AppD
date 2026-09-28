"use client";

import { useState } from "react";
import type { Messages } from "@/i18n/messages";
import { LoginForm } from "./LoginForm";
import { RegisterForm } from "./RegisterForm";

type AuthPanelProps = {
  messages: Messages;
};

type AuthTab = "login" | "register";

/**
 * Tarjeta de acceso embebida en la portada (estilo broker): pestañas
 * accesibles "Iniciar sesión" / "Crear cuenta" que montan el formulario
 * real correspondiente (LoginForm / RegisterForm, sin duplicar lógica).
 */
export function AuthPanel({ messages }: AuthPanelProps): React.JSX.Element {
  const landing = messages.landing;
  const [tab, setTab] = useState<AuthTab>("login");

  const activeTabId = tab === "login" ? "pestana-acceso" : "pestana-registro";

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setTab((current) => (current === "login" ? "register" : "login"));
  }

  return (
    <div className="rounded-xl border border-mist bg-white p-6 shadow-sm">
      <h2 className="text-xl font-bold tracking-tight">{landing.authTitle}</h2>
      <div
        role="tablist"
        aria-label={landing.authTitle}
        onKeyDown={handleKeyDown}
        className="mt-4 grid grid-cols-2 gap-1 rounded-lg bg-mist p-1"
      >
        <button
          type="button"
          role="tab"
          id="pestana-acceso"
          aria-selected={tab === "login"}
          aria-controls="panel-acceso"
          tabIndex={tab === "login" ? 0 : -1}
          onClick={() => setTab("login")}
          className={[
            "rounded-md px-4 py-2 text-sm font-semibold transition",
            tab === "login" ? "bg-ink text-white shadow-sm" : "text-ink hover:bg-white",
          ].join(" ")}
        >
          {landing.authTabLogin}
        </button>
        <button
          type="button"
          role="tab"
          id="pestana-registro"
          aria-selected={tab === "register"}
          aria-controls="panel-acceso"
          tabIndex={tab === "register" ? 0 : -1}
          onClick={() => setTab("register")}
          className={[
            "rounded-md px-4 py-2 text-sm font-semibold transition",
            tab === "register" ? "bg-ink text-white shadow-sm" : "text-ink hover:bg-white",
          ].join(" ")}
        >
          {landing.authTabRegister}
        </button>
      </div>
      <div
        role="tabpanel"
        id="panel-acceso"
        aria-labelledby={activeTabId}
        tabIndex={0}
        className="mt-6"
      >
        {tab === "login" ? <LoginForm messages={messages} /> : <RegisterForm messages={messages} />}
      </div>
    </div>
  );
}
