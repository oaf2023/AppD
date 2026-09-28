import type { NextConfig } from "next";

/*
 * CSP básica compatible con Next.js/Tailwind:
 * - `script-src 'self' 'unsafe-inline'`: Next emite scripts inline de
 *   arranque/hidratación sin nonce; sin 'unsafe-inline' la app no hidrata.
 * - `style-src 'self' 'unsafe-inline'`: Tailwind/Next inyectan estilos.
 * - `frame-ancestors 'none'` (+ X-Frame-Options) y `object-src 'none'`.
 * PENDIENTE: nonces por petición para endurecer script-src (fase posterior).
 */
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "object-src 'none'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
].join("; ");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Requerido para la imagen Docker (servidor Node autónomo).
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
        ],
      },
    ];
  },
};

export default nextConfig;
