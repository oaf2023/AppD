import { cookies } from "next/headers";

/**
 * Ayudas de autenticación del BFF (SOLO servidor: nunca importar desde cliente).
 *
 * - Los tokens viven en cookies httpOnly (`at` = access, `rt` = refresh).
 * - El navegador nunca ve los tokens en JS ni en `localStorage`.
 * - `GET /api/v1/me` y el resto de llamadas usan `${GATEWAY_URL}` directamente
 *   desde el servidor (sin rewrites inversos en `next.config.ts`).
 */

/** Cookie con el access token (corta duración, disponible en todo el sitio). */
export const ACCESS_COOKIE = "at" as const;
/** Cookie con el refresh token (restringida a `path=/api/auth`). */
export const REFRESH_COOKIE = "rt" as const;

/** Tiempo máximo de espera por llamada al gateway (el proxy interno usa 15 s). */
const GATEWAY_TIMEOUT_MS = 15_000;

/** Duración máxima de la cookie de refresco (30 días = TTL del backend). */
const REFRESH_COOKIE_MAX_AGE = 30 * 24 * 60 * 60;

export type UserOut = {
  id: string;
  email: string;
  status: string;
  roles: string[];
  email_verified: boolean;
  mfa_enabled: boolean;
  created_at: string;
};

export type TokenPairOut = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  session_id: string;
  user: UserOut;
};

export type RegisterOut = {
  user_id: string;
  email: string;
  status: string;
  email_verification_required: boolean;
};

/** Error estándar RFC 9457 (`application/problem+json`) del backend. */
export type ProblemDetail = {
  type?: string | undefined;
  title?: string | undefined;
  status?: number | undefined;
  detail?: string | undefined;
};

/** Base del gateway (solo servidor). En producción es obligatoria; en dev cae a localhost. */
export function gatewayUrl(): string {
  const raw = process.env.GATEWAY_URL;
  const value = raw === undefined ? "" : raw.trim().replace(/\/+$/, "");
  if (value !== "") return value;
  if (process.env.NODE_ENV === "production") {
    throw new Error("GATEWAY_URL no configurada en el servidor.");
  }
  return "http://localhost:8000";
}

/**
 * `Secure` solo cuando se pide explícitamente (`COOKIE_SECURE=true`).
 * En despliegue LAN se sirve por HTTP y `Secure` impediría guardar/recibir
 * las cookies; en producción HTTPS debe activarse.
 */
export function cookieSecure(): boolean {
  return process.env.COOKIE_SECURE === "true";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isTokenPair(value: unknown): value is TokenPairOut {
  if (!isRecord(value)) return false;
  return (
    typeof value["access_token"] === "string" &&
    typeof value["refresh_token"] === "string" &&
    typeof value["expires_in"] === "number" &&
    isRecord(value["user"])
  );
}

export function isMfaRequired(value: unknown): value is { mfa_required: boolean; mfa_token: string } {
  if (!isRecord(value)) return false;
  return value["mfa_required"] === true && typeof value["mfa_token"] === "string";
}

export function isUser(value: unknown): value is UserOut {
  if (!isRecord(value)) return false;
  return (
    typeof value["id"] === "string" &&
    typeof value["email"] === "string" &&
    typeof value["status"] === "string" &&
    Array.isArray(value["roles"]) &&
    typeof value["email_verified"] === "boolean" &&
    typeof value["mfa_enabled"] === "boolean" &&
    typeof value["created_at"] === "string"
  );
}

/** Extrae `{status, message}` de una respuesta de error (RFC 9457 o JSON genérico). */
export async function readUpstreamError(response: Response, fallback: string): Promise<{ status: number; message: string }> {
  let message = fallback;
  try {
    const data: unknown = await response.json();
    if (isRecord(data)) {
      const detail = data["detail"];
      const title = data["title"];
      if (typeof detail === "string" && detail !== "") message = detail;
      else if (typeof title === "string" && title !== "") message = title;
    }
  } catch {
    // Cuerpo no JSON: se conserva el mensaje genérico.
  }
  return { status: response.status, message };
}

/** Llamada al gateway con timeout fijo (15 s, como el proxy interno). */
export async function gatewayFetch(path: string, init: RequestInit): Promise<Response> {
  const base = gatewayUrl();
  return fetch(`${base}${path}`, { ...init, signal: AbortSignal.timeout(GATEWAY_TIMEOUT_MS) });
}

type CookieSetter = {
  set: (name: string, value: string, options: { httpOnly: boolean; sameSite: "lax"; secure: boolean; path: string; maxAge: number }) => void;
};

function cookieOptions(path: string, maxAge: number): { httpOnly: boolean; sameSite: "lax"; secure: boolean; path: string; maxAge: number } {
  return { httpOnly: true, sameSite: "lax", secure: cookieSecure(), path, maxAge };
}

/** Persiste el par de tokens tras login/refresh (rotación: sobrescribe ambas cookies). */
export function setAuthCookies(store: CookieSetter, pair: TokenPairOut): void {
  const accessMaxAge = Number.isFinite(pair.expires_in) && pair.expires_in > 0 ? Math.floor(pair.expires_in) : 900;
  store.set(ACCESS_COOKIE, pair.access_token, cookieOptions("/", accessMaxAge));
  store.set(REFRESH_COOKIE, pair.refresh_token, cookieOptions("/api/auth", REFRESH_COOKIE_MAX_AGE));
}

/** Borra ambas cookies (logout o sesión inválida). */
export function clearAuthCookies(store: CookieSetter): void {
  store.set(ACCESS_COOKIE, "", cookieOptions("/", 0));
  store.set(REFRESH_COOKIE, "", cookieOptions("/api/auth", 0));
}

async function fetchMe(accessToken: string): Promise<UserOut | null> {
  try {
    const response = await gatewayFetch("/api/v1/me", {
      headers: { authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    return isUser(data) ? data : null;
  } catch {
    return null;
  }
}

/**
 * Usuario de la sesión actual para Server Components (p. ej. `/panel`).
 * Lee la cookie `at` y consulta `GET /api/v1/me` en el gateway.
 * Sin rotación aquí: `cookies().set` no está permitido en Server Components;
 * la rotación vive en `GET /api/auth/session`. Si el access caducó, se
 * devuelve `null` y la página redirige a `/login` (PENDIENTE: middleware).
 */
export async function getSessionUser(): Promise<UserOut | null> {
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  if (access === undefined || access === "") return null;
  return fetchMe(access);
}
