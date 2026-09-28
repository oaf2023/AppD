import { NextRequest, NextResponse } from "next/server";
import { gatewayFetch, isMfaRequired, isTokenPair, setAuthCookies } from "@/lib/auth";

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{1,255}$/;

type LoginBody = {
  email: unknown;
  password: unknown;
};

function errorFromData(status: number, data: unknown, fallback: string): { status: number; message: string } {
  if (data !== null && typeof data === "object") {
    const record = data as Record<string, unknown>;
    const detail = record["detail"];
    const title = record["title"];
    if (typeof detail === "string" && detail !== "") return { status, message: detail };
    if (typeof title === "string" && title !== "") return { status, message: title };
  }
  return { status, message: fallback };
}

/**
 * `POST /api/auth/login` — BFF de acceso.
 * Reenvía al gateway (`POST /api/v1/auth/login`) y, con `TokenPairOut`,
 * guarda los tokens en cookies httpOnly. Con `MfaRequiredOut` responde 409
 * con `{mfa: true}` para que la UI muestre el aviso de doble factor.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: LoginBody;
  try {
    body = (await request.json()) as LoginBody;
  } catch {
    return NextResponse.json({ error: "Cuerpo de la petición inválido." }, { status: 400 });
  }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  // El backend (`LoginIn`) acepta `min_length=1`; el cliente exige 12 por
  // política (toda contraseña válida tiene ≥12 por `RegisterIn`). Aquí se
  // valida presencia/formato y el servidor tiene la última palabra.
  if (email === "" || !EMAIL_RE.test(email)) {
    return NextResponse.json({ error: "Introduce un correo electrónico válido." }, { status: 422 });
  }
  if (password === "") {
    return NextResponse.json({ error: "La contraseña es obligatoria." }, { status: 422 });
  }

  let upstream: Response;
  try {
    upstream = await gatewayFetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
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
    const { status, message } = errorFromData(
      upstream.status,
      data,
      "No se pudo iniciar sesión. Inténtalo de nuevo.",
    );
    return NextResponse.json({ error: message }, { status });
  }

  if (isMfaRequired(data)) {
    return NextResponse.json({ mfa: true }, { status: 409 });
  }
  if (!isTokenPair(data)) {
    return NextResponse.json({ error: "Respuesta inesperada del servidor. Inténtalo de nuevo." }, { status: 502 });
  }

  const response = NextResponse.json({ user: data.user });
  setAuthCookies(response.cookies, data);
  return response;
}
