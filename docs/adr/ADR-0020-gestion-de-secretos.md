# ADR-0020 — Gestión de secretos: env vars en local a Vault/KMS en producción

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | todos los servicios, CI/CD, frontend, infraestructura local y de producción |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §4 y §7 · `docs/phase0/M-tech-stack.md` §8 |

## Contexto

- `00-decisions.md` §4 fija: "env en local; Vault/KMS `REQUIERE PROVEEDOR` en producción; sin secretos en repo", y §7 lo eleva a invariante: nada de secretos en repo, logs, frontend ni documentación.
- `M-tech-stack.md` §8 detalla el camino: `.env` local no commiteado (`.env.example` con placeholders), GitHub Actions Secrets en CI con secret-scan bloqueante, y en producción un `SecretProvider` que aísle al código del mecanismo.
- `G-security-architecture.md` §5 añade los detalles operativos: pepper de Argon2id en secreto de entorno, rotación de claves JWT vía JWKS (`kid`), hash de API keys (nunca el secreto completo), inventario de secretos con dueño y caducidad, y la lista de "jamás en repo · logs · trazas OTel · frontend · respuestas de API · eventos · documentos".
- La evidencia de readiness exige inventario de secretos con caducidades y rotación automática demostrada antes de LIVE (`G-security-architecture.md` §11.1; `T-roadmap.md` gate F8: Vault/KMS en producción).
- No se ha evaluado ni seleccionado ningún proveedor de Vault/KMS: aplicar cualquier producto concreto sería inventar (regla de no-ficción, `00-decisions.md` §10).

## Decisión

1. **Interfaz única en el código: `SecretProvider`**. La aplicación solo conoce una interfaz (leer secreto por nombre, refrescar, y opcionalmente rotar) y **nunca** cómo ni de dónde se obtiene. Ni los servicios de dominio ni los adapters importan un cliente de proveedor concreto: el mecanismo se inyecta en la capa de composición/arranque. Cambiar de env var a Vault/KMS no toca código de negocio ni tests de dominio.
2. **Local (desarrollo)**: variables de entorno vía `.env` (en `.gitignore`) inyectado por docker compose; `.env.example` versionado **solo con placeholders** y nombres de variable. Credenciales locales son siempre sintéticas/efímeras; nada de credenciales reales en puestos de desarrollo (riesgo declarado en `G-security-architecture.md` §10).
3. **CI (GitHub Actions)**: secretos en GitHub Actions Secrets, accesibles solo a jobs de entornos autorizados; `pull_request` de forks sin secretos; `persist-credentials: false` en checkout; **secret-scan bloqueante** (gitleaks u OSS equivalente) en PR e historial, sin archivos `*.env` versionados (BUILD-005).
4. **Producción**: inyección desde **Vault/KMS → `REQUIERE PROVEEDOR`**. Mientras no se seleccione proveedor, la implementación productiva queda `PENDIENTE` y el arranque de los servicios en producción no puede completarse con secretos incrustados: solo por inyección de entorno o por el `SecretProvider` correspondiente.
5. **Rotación**: cada secreto tiene owner, TTL y runbook de rotación en el inventario. Rotaciones programadas y verificación de caducidad en CI; los JWT usan `kid` con solapamiento de claves vieja+nueva durante la ventana de validación; el pepper de Argon2id y los hashes de API keys se rotan según el inventario (con rehash en login para el pepper). La rotación es un procedimiento probado **antes** de LIVE, no un pendiente.
6. **Nunca en...** (invariante verificable): repo (incluidos README, runbooks, ejemplos y ADRs) · logs · trazas/métricas OTel · frontend (bundle Next.js, `NEXT_PUBLIC_*` no lleva secretos jamás) · respuestas de API · eventos de Redpanda ni DLQ · imágenes Docker · capturas de pantalla de soporte. El logger aplica el redactor de campos sensibles (`password`, `token`, `secret`, `authorization`, `cookie`, `otp`) previsto en `G-security-architecture.md` §9.
7. **Mínimo privilegio por secreto**: credencial por servicio y por entorno (no compartida entre 13 servicios), scopes mínimos, y separación DEMO/LIVE (`ADR-0012`): un secreto de sandbox no sirve en LIVE.
8. **Verificación continua**: secret-scan + regla de "no secretos en `resource.attributes`/spans" + test que comprueba que la configuración se resuelve desde `SecretProvider` (no desde literales en el código de dominio).

## Consecuencias

### Positivas

- Rotación y revocación posibles sin re-desplegar código ni reescribir `.env` en cada servicio (una vez resuelto el proveedor productivo).
- El código de dominio queda desacoplado del mecanismo: migrar de env vars a un gestor de secretos no toca lógica ni tests, y facilita auditar "qué secretos existen y quién los usa".
- Fugas detectadas en CI antes del merge (secret-scan) y menor valor de un repositorio o log filtrado (no contienen secretos).
- Coherencia con los gates: inventario + rotación demostrable son prerrequisito explícito del gate LIVE.
- Reutilizable en cualquier entorno (local, CI, staging, producción) con la misma interfaz.

### Negativas

- Hasta seleccionar proveedor (`REQUIERE PROVEEDOR`), la producción real queda bloqueada en su configuración de secretos: no se puede declarar resuelto el control.
- Dependencia de un componente externo crítico cuando se adopte Vault/KMS: disponibilidad y rotación pasan a ser parte del SLA operativo (mitigación: caché local del secreto con TTL corto para resistir cortes breves).
- La regla "nunca secretos en frontend" limita funcionalidades que requieren claves en cliente → solo se admite material **público** por diseño (p. ej. claves anónimas de API de terceras partes si legal lo aprueba), nunca secretos de plataforma.
- El redactor de logs puede sobre-redactar y dificultar la depuración (mitigación: tests de redacción y casos de excepción revisados).
- Inventario y rotaciones añaden operación recurrente (dueños, caducidades, drills) que hay que mantener vivo.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Secretos en el repo (config cifrada commiteada) | Viola `00-decisions.md` §7; la clave de cifrado termina también en el repo o en el historial; el secret-scan lo bloquearía. |
| Gestor de secretos SaaS desde Fase 1 | `REQUIERE PROVEEDOR` sin evaluación de seguridad, coste, residencia ni lock-in; la interfaz `SecretProvider` permite adoptarlo después sin reescritura. |
| Passphrase compartida del equipo sobre archivos cifrados | Secreto único compartido, sin rotación individual, sin auditoría de acceso y expuesta en cada puesto de desarrollo. |
| Variables de entorno también en producción (solo `.env` de servidor) | Sin rotación automatizada, sin inventario central, secretos en disco de cada host y propagados a imágenes/scripts; no cumple el gate de rotación demostrada. |
| Secretos accesibles desde el frontend para simplificar integraciones | Los secretos de plataforma quedarían en el bundle de todo usuario; prohibido por `00-decisions.md` §7. |

## Referencias

- `docs/phase0/00-decisions.md` §4 (env local, Vault/KMS `REQUIERE PROVEEDOR`), §7 (nada de secretos en repo/logs/frontend)
- `docs/phase0/M-tech-stack.md` §8 (secrets), §11.1 (secret-scan, pin de actions)
- `docs/phase0/G-security-architecture.md` §5 (criptografía y secretos), §9 (política de no-logging), §11.1 (gate de inventario/rotación)
- `docs/phase0/W-build-now.md` BUILD-005 (secret-scan bloqueante)
- `docs/phase0/T-roadmap.md` (gate F8: Vault/KMS en producción, rotación automática)
- `docs/phase0/V-risk-register.md` (R-004/R-022: secretos de sesión y tokens)
- ADR-0013 (sin secretos en telemetría), ADR-0012 (separación DEMO/LIVE de credenciales)
