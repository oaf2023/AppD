import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  clearAuthCookies,
  gatewayFetch,
  isTokenPair,
  isUser,
  setAuthCookies,
} from "@/lib/auth";
import type { UserOut } from "@/lib/auth";

async function fetchMe(accessToken: string): Promise<{ status: number; user: UserOut | null }> {
  const response = await gatewayFetch("/api/v1/me", {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) return { status: response.status, user: null };
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  return { status: response.status, user: isUser(data) ? data : null };
}

async function tryRefresh(refreshToken: string): Promise<{ access: string; refresh: string; expiresIn: number } | null> {
  const response = await gatewayFetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) return null;
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!isTokenPair(data)) return null;
  return { access: data.access_token, refresh: data.refresh_token, expiresIn: data.expires_in };
}

/**
 * `GET /api/auth/session` — sesión actual para el cliente.
 * Lee la cookie `at` y consulta `GET /api/v1/me`; si el access caducó (401)
 * intenta un refresh con `rt` (rotación: fija cookies nuevas) y reintenta
 * `/me` una vez. Si todo falla responde `{user: null}` y borra las cookies.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const access = request.cookies.get(ACCESS_COOKIE)?.value ?? "";
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value ?? "";

  if (access !== "") {
    try {
      const first = await fetchMe(access);
      if (first.user !== null) return NextResponse.json({ user: first.user });
      if (first.status !== 401 || refresh === "") {
        const response = NextResponse.json({ user: null });
        clearAuthCookies(response.cookies);
        return response;
      }
    } catch {
      return NextResponse.json({ user: null });
    }
  }

  if (refresh === "") {
    return NextResponse.json({ user: null });
  }

  try {
    const rotated = await tryRefresh(refresh);
    if (rotated === null) {
      const response = NextResponse.json({ user: null });
      clearAuthCookies(response.cookies);
      return response;
    }
    const retry = await fetchMe(rotated.access);
    if (retry.user === null) {
      const response = NextResponse.json({ user: null });
      clearAuthCookies(response.cookies);
      return response;
    }
    const response = NextResponse.json({ user: retry.user });
    setAuthCookies(response.cookies, {
      access_token: rotated.access,
      refresh_token: rotated.refresh,
      token_type: "bearer",
      expires_in: rotated.expiresIn,
      session_id: "",
      user: retry.user,
    });
    return response;
  } catch {
    return NextResponse.json({ user: null });
  }
}
