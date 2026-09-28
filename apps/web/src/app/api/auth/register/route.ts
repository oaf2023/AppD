import { NextRequest, NextResponse } from "next/server";
import { gatewayFetch } from "@/lib/auth";
import type { RegisterOut } from "@/lib/auth";

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{1,255}$/;

type RegisterBody = {
  email: unknown;
  password: unknown;
  jurisdiction: unknown;
  accept_terms: unknown;
};

function isRegisterOut(value: unknown): value is RegisterOut & { dev_verification_token?: unknown } {
  if (value === null || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record["user_id"] === "string" &&
    typeof record["email"] === "string" &&
    typeof record["status"] === "string" &&
    typeof record["email_verification_required"] === "boolean"
  );
}

/**
 * `POST /api/auth/register` — BFF de registro.
 * Valida el contrato (`RegisterIn`: email, contraseña ≥12, jurisdicción
 * obligatoria, `accept_terms`) y reenvía al gateway
 * (`POST /api/v1/auth/register`). Devuelve un subconjunto seguro de
 * `RegisterOut`: `dev_verification_token` (solo local/test, sink MOCK) nunca
 * sale hacia el cliente.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: RegisterBody;
  try {
    body = (await request.json()) as RegisterBody;
  } catch {
    return NextResponse.json({ error: "Cuerpo de la petición inválido." }, { status: 400 });
  }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  const jurisdiction = typeof body.jurisdiction === "string" ? body.jurisdiction.trim().toUpperCase() : "";
  const acceptTerms = body.accept_terms === true;

  if (email === "" || !EMAIL_RE.test(email)) {
    return NextResponse.json({ error: "Introduce un correo electrónico válido." }, { status: 422 });
  }
  if (password.length < 12) {
    return NextResponse.json({ error: "La contraseña debe tener al menos 12 caracteres." }, { status: 422 });
  }
  if (password.length > 256) {
    return NextResponse.json({ error: "La contraseña supera la longitud máxima (256)." }, { status: 422 });
  }
  if (jurisdiction === "" || jurisdiction.length > 8) {
    return NextResponse.json({ error: "La jurisdicción es obligatoria (código de hasta 8 caracteres)." }, { status: 422 });
  }
  if (!acceptTerms) {
    return NextResponse.json({ error: "Debes aceptar los términos y condiciones." }, { status: 422 });
  }

  let upstream: Response;
  try {
    upstream = await gatewayFetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password, jurisdiction, accept_terms: true }),
    });
  } catch {
    return NextResponse.json(
      { error: "Servicio de autenticación no disponible. Inténtalo de nuevo." },
      { status: 503 },
    );
  }

  let data: unknown = null;
  try {
    data = await upstream.json();
  } catch {
    data = null;
  }

  if (!upstream.ok) {
    let message = "No se pudo crear la cuenta. Inténtalo de nuevo.";
    if (data !== null && typeof data === "object") {
      const record = data as Record<string, unknown>;
      const detail = record["detail"];
      const title = record["title"];
      if (typeof detail === "string" && detail !== "") message = detail;
      else if (typeof title === "string" && title !== "") message = title;
    }
    return NextResponse.json({ error: message }, { status: upstream.status });
  }

  if (!isRegisterOut(data)) {
    return NextResponse.json({ error: "Respuesta inesperada del servidor. Inténtalo de nuevo." }, { status: 502 });
  }

  return NextResponse.json(
    {
      user_id: data.user_id,
      email: data.email,
      status: data.status,
      email_verification_required: data.email_verification_required,
    },
    { status: 201 },
  );
}
