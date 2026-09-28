# ADR-0008 — Autenticación: JWT de acceso corto + refresh rotativo con detección de reuso; verdad de la sesión en Redis/PostgreSQL

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0004 (versionado/headers), ADR-0009 (ids), ADR-0010 (idempotencia)

## Contexto

`00-decisions.md` §7 fija dos invariantes: JWT de acceso **≤ 15 min** y refresh token **rotativo con detección de reuso**, además de Argon2id para passwords. El `gateway` valida en el edge para no llamar a `identity` en cada request; hay PWA, clientes API y llamadas servicio-a-servicio. Hay que decidir dónde vive la verdad de la sesión y qué hacer frente a la alternativa clásica de sesiones server-side puras, sobre todo en la ventana en la que un JWT emitido sigue siendo criptamente válido aunque la sesión esté revocada.

## Decisión

Se adopta un **modelo híbrido**: tokens firmados para validación rápida + estado de sesión persistido. La verdad de la sesión se reparte con responsabilidades claras:

| Capa | Qué guarda | Rol |
|---|---|---|
| **PostgreSQL `identity.sessions`** | `session_id` (UUIDv7), `created_at`, `last_seen_at`, `ip_hash`, `device_id`, `revoked_at`, `mfa_state`, familia de refresh | **Fuente de verdad duradera**: la sesión existe, está viva o revocada |
| **Redis 7** | denylist de `jti`/`sid` con TTL = tiempo restante del token; caché de sesión activa; contadores de rate limit; nonces de MFA | **Estado caliente de validación**: revocación en < 5 s; **nunca** fuente de verdad (pérdida por reinicio aceptada y reconstruida desde `identity`) |
| **JWT de acceso** | claims mínimos: `sub`, `sid`, `jti`, `iss`, `aud`, `iat`, `exp`, `scope[]`, `roles[]`, `mode` | **Credencial de corta vida** validable localmente en el gateway vía JWKS |

**Dónde vive la verdad de la sesión:** Redis concentra la verdad **operativa de validación** (denylist de `jti`/`sid`, caché de sesión activa) que el gateway consulta en cada request con latencia < 5 s; la verdad **duradera** (qué sesiones existen, cuándo se crearon y cuándo se revocaron) vive en PostgreSQL `identity.sessions`. Redis **nunca es fuente de verdad**: si se vacía, se reconstruye desde `identity` y los refresh pendientes se invalidan por seguridad (`M-tech-stack.md` §5).

Reglas:

1. **Access JWT ≤ 15 min**, sin renovación silenciosa por refresh; `exp` real. Un solo algoritmo configurado, con `kid` y JWKS con solapamiento de claves para rotación; rechazo explícito de `none` y de `alg` distinto al configurado. La elección EdDSA vs RS256 queda `DECIDIR` al implementar Fase 1 (`G-security-architecture.md` §3.2).
2. **Refresh opaco** (aleatorio ≥ 256 bits), rotativo: cada uso emite uno nuevo y el anterior queda invalidado; cada refresh pertenece a una **familia** (`family_id`). Uso de un token ya rotado ⇒ **invalidación inmediata de la familia completa + revocación de la sesión + evento `auth.refresh.reuse_detected` + notificación al usuario**. TTL deslizante corto (ventana 30–90 días a fijar al implementar, con detección de inactividad).
3. **Almacenamiento en cliente**: refresh en cookie `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth` (scope mínimo); access token en memoria de JavaScript. **Prohibido** `localStorage` para refresh.
4. **Revocación**: denylist en Redis por `jti`/`sid` con latencia objetivo < 5 s; `logout` revoca la sesión actual, `logout-all` exige step-up MFA. Ante caída de Redis: **fail-closed** en `auth/*` (503 + `Retry-After`) y fail-open documentado solo en lecturas.
5. **El servicio destino siempre revalida** pertenencia y scope del recurso (no se confía ciegamente en el gateway).
6. **Servicio-a-servicio**: JWT de servicio con TTL ≤ 5 min (`iss=platform-internal`, `sub=svc:<nombre>`), sin heredar scopes de usuario; mTLS como objetivo en K8s; prohibido propagar cookies o refresh tokens entre servicios.

## Consecuencias

### Positivas

- Validación barata en el edge sin llamada síncrona a `identity` en cada request; escala horizontal sin sesión pegajosa.
- Revocación efectiva en segundos (denylist) pese a usar JWT, y detección de robo de refresh por reuso de familia.
- La verdad de la sesión es consultable y auditable en PostgreSQL (login history, sesiones activas, dispositivos).
- Coherente con API keys (scope + IP allowlist + expiración) y con step-up MFA para acciones de efecto.

### Negativas

- Dos stores que deben conciliar: PostgreSQL es la verdad, Redis es caché con TTL; un desajuste de TTL deja tokens vivos más tiempo del deseado.
- La denylist es estado compartido en el camino crítico de auth (punto de fallo): se asume fail-closed y se monitoriza.
- Ventana residual ≤ 15 min en la que un JWT revocado sigue siendo válido si no se consulta la denylist en esa ruta (mitigado: denylist obligatoria en rutas sensibles).
- La rotación con familias y detección de reuso añade lógica compleja en `identity` (falsos positivos ante reintentos de red del cliente ⇒ el refresh debe tolerar reintento con la misma clave de forma acotada).
- La elección de algoritmo JWT sigue pendiente de decidir.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Sesiones server-side puras** (cookie + lookup por request) | Revocación instantánea sin denylist y modelo más simple, pero obliga a que gateway y todos los servicios consulten `identity`/Redis en cada request: acoplamiento duro, punto único de latencia y disponibilidad, y peor encaje con clientes API/móviles y con API keys. |
| **JWT largo (horas/días) sin refresh** | Ventana de robo enorme: un token filtrado da acceso hasta expirar; incompatible con la detección de reuso exigida. |
| **Token opaco + introspección por request** | Cada request depende de la disponibilidad de `identity`; latencia adicional por hop sin necesidad. |
| **JWT sin denylist (solo `exp`)** | La revocación real (logout, robo, cambio de rol, MFA) tardaría hasta 15 min: inaceptable para retiros y acciones admin. |
| **Passkeys/WebAuthn como único factor** | `PENDIENTE` (`00-decisions.md` §7); en Fase 1 MFA es TOTP opcional tras flag. |

## Referencias

- `docs/phase0/00-decisions.md` §7 (JWT ≤ 15 min, refresh rotativo con reuso).
- `docs/phase0/G-security-architecture.md` §3.1 (Argon2id), §3.2 (tokens y sesiones), §3.4 (rate limit/fail-closed), §7 (identidad de servicio), §9 (eventos de seguridad).
- `docs/phase0/Q-api-map.md` §1.6 (cabeceras), §1.7 (scopes y reglas), §2.2 (rutas de auth), §3.1 (auth interna).
- `docs/phase0/O-database-strategy.md` §2 (tablas `sessions`, `devices`, `login_history`).
- `docs/adr/ADR-0009-identidad-y-ids.md`, `docs/adr/ADR-0010-idempotencia-primero.md`.

> **Nota de numeración:** `A-executive-summary.md` §4 y `M-tech-stack.md` §6 citan esta decisión como «ADR-0009». Su ubicación canónica es este ADR-0008.
