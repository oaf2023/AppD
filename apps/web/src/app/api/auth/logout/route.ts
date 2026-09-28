import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearAuthCookies, gatewayFetch } from "@/lib/auth";

/**
 * `POST /api/auth/logout` — cierre de sesión.
 * Llama al gateway (`POST /api/v1/auth/logout`, ruta protegida: requiere
 * `Authorization: Bearer <access>` más el refresh en el cuerpo) y, en todo
 * caso, borra las cookies httpOnly para que la sesión muera en el navegador.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const access = request.cookies.get(ACCESS_COOKIE)?.value ?? "";
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value ?? "";

  if (access !== "") {
    try {
      await gatewayFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${access}`,
        },
        body: JSON.stringify({ refresh_token: refresh === "" ? null : refresh }),
      });
    } catch {
      // El logout del navegador se completa igual: las cookies se borran abajo.
    }
  }

  const response = NextResponse.json({ ok: true });
  clearAuthCookies(response.cookies);
  return response;
}
