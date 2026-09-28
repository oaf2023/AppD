/**
 * Inicialización de observabilidad del lado servidor (Next.js instrumentation).
 *
 * Fase 1 — foundation: STUB documentado e intencionadamente vacío.
 *
 * - Next.js invoca `register()` una vez al arrancar el servidor cuando existe
 *   este archivo en `src/` (ver `M-tech-stack.md` §2/§7 y la convención de
 *   `instrumentation.ts` de Next.js 15).
 * - La inicialización real del SDK de OpenTelemetry para Node.js
 *   (trazas/métricas/logs hacia el Collector) se añadirá en una fase
 *   posterior, junto con las dependencias OTel y la configuración del
 *   collector. NO se añade ninguna dependencia OTel todavía.
 * - No debe importarse desde componentes ni usarse en el cliente: solo corre
 *   en el entorno Node.js del servidor.
 */
export async function register(): Promise<void> {
  // Intencionadamente vacío en Fase 1.
}
