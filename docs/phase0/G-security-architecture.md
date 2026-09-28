# G — Arquitectura de Seguridad (Security Architecture)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`
Fuente canónica: `00-decisions.md` §7 (invariantes de seguridad) · Complementos: `Q-api-map.md` §1.6–1.8 y §5, `P-event-catalog.md`, `O-database-strategy.md`, `W-build-now.md`, `X-blocked-to-live.md`

> **Regla de lectura**: este documento define el **diseño de seguridad objetivo** y los controles a implementar. No es una afirmación de cumplimiento ni de certificación. Ninguna norma (OWASP ASVS, PCI DSS, SOC 2, ISO 27001, GDPR) está **certificada ni auditada**: el nivel ASVS L2 es un **objetivo de diseño** y su verificación externa es `PENDIENTE`. Todo control se etiqueta con su estado real (`IMPLEMENTADO` / `PARCIAL` / `MOCK` / `PENDIENTE` / `REQUIERE PROVEEDOR` / `REQUIERE LICENCIA/REGULACIÓN`). A la fecha de este documento el repositorio contiene documentación de Fase 0; por tanto **todos los controles de código son `PENDIENTE` hasta la ejecución de Fase 1** salvo indicación.
> No se seleccionan proveedores, certificados, CA ni licencias en este documento (regla de no-ficción, `00-decisions.md` §10).

---

## 0. Principios rectores

| # | Principio | Consecuencia operativa |
|---|---|---|
| P1 | Defense in depth | Ningún control único es crítico: edge + servicio + datos + auditoría en cada flujo sensible |
| P2 | Denegación por defecto | Toda ruta, scope, rol y red parte en `deny`; habilitar es explícito y auditado |
| P3 | Mínimo privilegio | Credenciales, scopes, roles, redes y cuotas al mínimo necesario y por tiempo limitado |
| P4 | No confiar en el borde | El gateway valida JWT/rate limit/headers, pero **cada servicio revalida** pertenencia, scope y modo (`Q-api-map` §3.1) |
| P5 | Sin secretos en el repo | Secrets solo por entorno (`.env` local no versionado; Vault/KMS `REQUIERE PROVEEDOR` en producción) |
| P6 | Trazabilidad total | `request_id` + `correlation_id` + `session_id` en toda acción crítica hacia `audit` |
| P7 | No-ficción | Lo no construido se marca `PENDIENTE`; nunca se afirma protegido/cumplido lo no verificado |
| P8 | Seguridad por diseño de datos | Clasificación, minimización, retención y cifrado definidos antes de persistir (`data-governance`) |

---

## 1. Modelo de amenazas por capa

Formato: **amenaza → control concreto → dónde se implementa**. Estado = estado esperado en Fase 1.

### 1.1 Navegador / PWA (Next.js 15)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| XSS almacenado/reflejado (React dangerouslySetInnerHTML, markdown de usuario) | Escapado por defecto de React; `dangerouslySetInnerHTML` prohibido en lint salvo allowlist sanitizada (DOMPurify) | `apps/web` (ESLint rule) + revisión PR | `PENDIENTE` |
| Robo de tokens por script inyectado | Cookies `HttpOnly` + `Secure` + `SameSite=Lax` para refresh; access token en memoria JS, **nunca** `localStorage` | `gateway` (set-cookie) + `apps/web` (almacenamiento en memoria) | `PENDIENTE` |
| CSRF sobre acciones autenticadas | `SameSite=Lax` + double-submit token en mutaciones HTML + `Origin`/`Sec-Fetch-Site` validados en gateway | `gateway` middleware | `PENDIENTE` |
| Clickjacking | `X-Frame-Options: DENY` (o `frame-ancestors 'none'` en CSP) | `gateway` (§6) | `PENDIENTE` |
| Manifest/service worker malicioso (PWA) | `serviceworker` acotado a origen propio; sin `importScripts` externo; actualización versionada y cache invalidado tras logout | `apps/web` (`public/`, registro SW) | `PENDIENTE` |
| Fuga de datos por terceros (analytics, fonts, CDNs) | CSP `default-src 'self'`; sin CDNs de terceros; telemetría solo OTel propio sin PII | `gateway` CSP + `apps/web` | `PENDIENTE` |
| Suplantación de dominio / phishing | Marcador literal `[DOMAIN]` hasta definición real (marca `MonedasAR` ya definida); HSTS solo con dominio real (§6) | `00-decisions.md` §1 | `PENDIENTE` |
| Robo de credenciales en formulario (autocompletado/extensiones) | `autocomplete` correcto (`current-password`/`one-time-code`), sin logging de body en auth | `apps/web` + `services/identity` | `PENDIENTE` |
| Replay de respuestas sensibles | `Cache-Control: no-store` en rutas auth/identidad | `gateway` (§6) | `PENDIENTE` |

### 1.2 Gateway (edge `/api/v1/`)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| Superficie interna expuesta | `/internal/*` bloqueado en edge con `404` (no `403`, anti-descubrimiento) | `services/gateway` router | `PENDIENTE` |
| Tokens inválidos/expirados/forged | Verificación de firma, `exp`, `nbf`, `iss`, `aud`, `alg` (rechazo de `none` y de confusión de algoritmo) vía JWKS de `identity` | `services/gateway` auth middleware | `PENDIENTE` |
| Flood / DoS de aplicación | Sliding window en Redis por IP, token, ruta y sujeto; `429` + `Retry-After` (§8) | `services/gateway` + Redis | `PENDIENTE` |
| Enrutado a rutas no públicas | Allowlist de rutas servidas; todo lo no declarado → `404` | `services/gateway` | `PENDIENTE` |
| Falta de trazabilidad | Generación/propagación de `X-Request-Id` y `X-Correlation-Id`; OTel trace id correlacionado | `services/gateway` + OTel | `PENDIENTE` |
| Falta de cabeceras de seguridad | Inyección única de todas las cabeceras §6 en respuesta | `services/gateway` | `PENDIENTE` |
| Pérdida de eventos de seguridad | Emisión de eventos de seguridad §9 (login fallido, etc.) con `Idempotency`/outbox | `services/identity` → outbox → Redpanda → `services/audit` | `PENDIENTE` |

### 1.3 Servicios de aplicación (`identity`, `audit`)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| SQLi | SQLAlchemy 2 con params vinculados; **prohibido** `text()` con f-string; raw SQL solo con allowlist y revisión; IDs como UUID tipados | `services/*/repository` | `PENDIENTE` |
| Mass assignment | Modelos Pydantic de request separados de los de persistencia; campos sensibles (`role`, `is_verified`, `balance`) jamás en input público | `services/identity/schemas` | `PENDIENTE` |
| Broken object-level authorization (BOLA) | Filtro obligatorio por `subject_id`/`account_id` del token; recurso ajeno → `404` idéntico a inexistente | `services/*/dependencies` | `PENDIENTE` |
| Escalada de privilegios | RBAC §4 evaluado en servicio; roles solo por tabla con migración + auditoría; jamás por claim editable por cliente | `services/identity` | `PENDIENTE` |
| Command/XXE/SSRF | Sin `subprocess` con input de usuario; sin `lxml` con entidades externas; HTTP saliente solo a hosts de config con allowlist y sin redirects a IP privadas (§2) | `services/*` | `PENDIENTE` |
| DoS por payloads | Límite de cuerpo 1 MiB (8 MiB KYC) y validación Pydantic estricta | `gateway` + servicios | `PENDIENTE` |
| Acceso directo a datos entre servicios | Cada servicio con su schema PG y credencial propia; sin acceso cruzado a tablas (ADR-0005) | `infrastructure/compose` + migraciones | `PENDIENTE` |
| Alteración del log de auditoría | Tabla append-only con `REVOKE UPDATE, DELETE`, triggers anti-modificación, hash encadenado por entrada | `services/audit` + migración | `PENDIENTE` |

### 1.4 Datos (PostgreSQL 17, Redis 7, Redpanda)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| Lectura de volúmenes en claro | Cifrado en reposo (§5); en local Docker Desktop/WSL depende del host → declarado y documentado | Infraestructura | `REQUIERE PROVEEDOR` (cloud) / `PENDIENTE` (local) |
| Backup expuesto / sin cifrado | Backups cifrados, probados con restore; retención definida | Infraestructura | `PENDIENTE` (runbook BUILD-062) |
| Extracción de hashes/sesiones de Redis | Redis sin exposición a host, sin `FLUSHALL` en prod, `requirepass`/ACL por usuario y por servicio, TLS entre servicios `PENDIENTE` | `infrastructure/compose` | `PARCIAL` local / `PENDIENTE` |
| Replay/inyección de eventos | Topic ACLs por productor/consumidor; envelope con `event_id` idempotente y schema versionado | Redpanda + `P-event-catalog.md` | `PENDIENTE` |
| PII en logs/cache | Minimización, redacción y TTL corto (§9) | servicios + logging config | `PENDIENTE` |
| Enumeración de IDs | UUIDv7/aleatorio no secuencial en toda entidad expuesta (00-decisions §7) | modelos de dominio | `PENDIENTE` |
| Corrupción financiera | Ledger append-only, `NUMERIC(38,18)`, sin `float`, sin UPDATE/DELETE (L-ledger) | `services/ledger` (Fase 2) | `PENDIENTE` (F2) |

### 1.5 Infraestructura docker local (compose)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| Puertos de datos publicados en `0.0.0.0` | Solo gateway (y opcionalmente UI de obs) publicados; Postgres/Redis/Redpanda/OTel solo en red interna del compose | `infrastructure/compose/*.yaml` | `PENDIENTE` |
| Contenedores como root | `USER` no-root, filesystem read-only donde sea posible, `cap_drop: ALL`, `security_opt: no-new-privileges` | Dockerfiles + compose | `PENDIENTE` |
| Secretos en `docker-compose.yaml` | `env_file` no versionado (`.env.example` versionado sin valores) + secret-scan en CI (BUILD-005) | compose + CI | `PENDIENTE` |
| Volúmenes con permisos amplios | Volumenes con dueño del servicio; sin `-v /:/host` ni sockets Docker montados | compose | `PENDIENTE` |
| Dependencias desactualizadas | Pines de versión digest, renovación controlada, escaneo de CVE con umbral que falla CI (BUILD-005) | CI | `PENDIENTE` |
| Imágenes de terceros no verificadas | Imágenes de registro oficial, pin por digest, SBOM por imagen (BUILD-003/005) | CI | `PENDIENTE` |
| Fuga de datos a internet desde local | Sin credenciales reales en local; datos DEMO sintéticos; `live_trading=false` | config + flags | `PENDIENTE` |

### 1.6 CI/CD (GitHub Actions)

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| Secretos filtrados | Secret-scan bloqueante (gitleaks u OSS equivalente) en todo PR + historial; `.env` en `.gitignore` | `.github/workflows` | `PENDIENTE` |
| Código malicioso en PR de fork | `pull_request` sin secrets; entorno aprobado manual para jobs con credenciales; `persist-credentials: false` en checkout | workflows | `PENDIENTE` |
| Dependencias comprometidas | Lockfiles, pin de actions por SHA, renovación revisada, escaneo SBOM/CVE | workflows | `PENDIENTE` |
| Artefactos no reproducibles | Build por servicio con versionado de imagen y etiqueta de commit; sin `latest` en despliegue | workflows | `PENDIENTE` |
| Pipeline sin gates de seguridad | Jobs obligatorios: lint, typecheck, tests, escaneo estático, secret-scan, escaneo de imagen, `terraform validate`, diff de OpenAPI | workflows | `PENDIENTE` |
| Rotura de fronteras del monorepo | Lint de dependencias cross-dominio (BUILD-001) | CI + ESLint/Ruff | `PENDIENTE` |
| Despliegue sin aprobación | Protección de rama `main` + revisión obligatoria; despliegue a entorno separado con approval `PENDIENTE` | GitHub settings | `PENDIENTE` |

### 1.7 Supply chain

| Amenaza | Control concreto | Dónde se implementa | Estado |
|---|---|---|---|
| Paquete npm/PyPI malicioso | Lockfiles + registry oficial + pins; sin instalación post-install no revisada | `package-lock.json` / `uv.lock` | `PENDIENTE` |
| Imagen Docker alterada | Digest pin + verificación de origen (SBOM) | CI/infra | `PENDIENTE` |
| Acción de GitHub comprometida | Pin por SHA completo, no por tag | workflows | `PENDIENTE` |
| Script de instalación malicioso en dev | Ambiente reproducible documentado; sin `curl \| sh` en scripts de build | `scripts/` | `PENDIENTE` |
| Proveedor externo sin contrato | Adapter + mock + placeholder (`00-decisions` §10); registro de proveedor y fecha de verificación | `X-blocked-to-live.md` | `PENDIENTE` |
| Falta de inventario | SBOM por imagen/servicio publicado en CI (BUILD-003/005) | CI | `PENDIENTE` |

---

## 2. Controles OWASP ASVS L2 (objetivo de diseño; no certificado)

Ubicación: **GW** = se aplica en `gateway`; **SVC** = se aplica en el servicio dueño de la ruta; **AMBOS** = defensa en capas (el servicio nunca asume que el gateway ya lo hizo). Cada control tiene test negativo asociado en CI.

| # | Riesgo (ASVS) | Control técnico | Ubicación | Fase |
|---|---|---|---|---|
| 1 | SQL Injection | ORM SQLAlchemy 2 con parámetros vinculados; prohibición de f-strings en SQL (lint/rule); `text()` solo con allowlist revisada; IDs parametrizados como UUID; WAF-ish: rechazo de payloads `UNION/;--` en el edge como señal (no como único control) | AMBOS | 1 |
| 2 | XSS | React escaping + sanitizador HTML si se admite markdown; CSP estricta con nonce (§6); `X-Content-Type-Options: nosniff`; cookies sin acceso desde JS (HttpOnly) | GW (CSP) + SVC (render) | 1 |
| 3 | CSRF | `SameSite=Lax` en cookies de sesión + validación de `Origin`/`Sec-Fetch-Site` en mutaciones + token double-submit para flujos con cookie; API keys y Bearer no CSRF-able por diseño | GW (validación) + SVC (mutaciones) | 1 |
| 4 | SSRF | Sin URLs arbitrarias de usuario en fetchers; allowlist de hosts externos desde config; bloqueo de rangos privados/loopback/metadata (`127.0.0.0/8`, `10/8`, `169.254/16`, `100.64/10`, `::1`); sin seguimiento de redirects a hosts no allowlistados | SVC (adapters) + GW (validación de URL en input) | 1 |
| 5 | XXE | Parser XML deshabilitado por defecto; si XML es obligatorio: `defusedxml`/deshabilitar entidades externas y DTD; límite de tamaño | SVC | 1 |
| 6 | Command Injection | Sin `shell=True`; sin ejecución de binarios con input de usuario; paths saneados (`Path.resolve` + allowlist de directorio); sin `eval`/`pickle` sobre datos externos | SVC | 1 |
| 7 | Credential Stuffing | Rate limit por IP + por cuenta (§8); backoff exponencial y lock temporal (§3); respuestas genéricas de login (sin enumeración de usuario); detección de patrones de password; `login_history` y alerta | GW (tasa) + SVC (cuenta) | 1 |
| 8 | Brute Force (online/offline) | Sliding window Redis; Argon2id con parámetros costosos (§3) que encarecen offline; bloqueo progresivo; MFA tras flag; rate limit de `refresh` y `verify-email` | GW + SVC | 1 |
| 9 | Session Fixation | `session_id` nuevo e inmutable tras cada login exitoso; nunca aceptar `session_id` preexistente del cliente; rotación de refresh en cada emisión | SVC (`identity`) | 1 |
| 10 | Broken Access Control | RBAC §4 + scope por recurso + filtro por `subject_id` + `404` anti-enumeración + denegación por defecto + tests negativos por rol en CI | SVC (decisión) + GW (scope) | 1 |
| 11 | Mass Assignment | DTO de entrada explícito y cerrado; campos de privilegio/estado solo en rutas admin con rol; validación Pydantic estricta (`extra="forbid"`) | SVC | 1 |
| 12 | API Abuse / scraping / bots | Rate limit por IP/usuario/ruta + quotas de negocio + `Idempotency-Key` en flujos financieros + límites de concurrencia WS + límite de rango de consulta (≤90 días) + respuesta uniforme en errores | GW (principal) + SVC (refuerzo) | 1 |
| 13 | Replay (tokens y peticiones) | JWT `jti` + `exp` ≤15 min; denylist de `jti` en revocación; refresh rotativo con detección de reuso; `Idempotency-Key` + hash de solicitud en mutaciones financieras; nonce en webhooks entrantes con `timestamp` dentro de ventana | GW + SVC | 1 |
| 14 | Webhook Spoofing | Firma HMAC-SHA256 en header, verificada con comparación en tiempo constante, ventana temporal y `Idempotency-Key`; IP allowlist del proveedor cuando exista; sin JWT (autenticación por firma) | SVC (`payments` F6; plantilla en F1) | 2+/6 |
| 15 | Cryptographic Failure | TLS obligatorio (§5), Argon2id, cifrado en reposo, sin datos sensibles en claro, sin MD5/SHA1 en credenciales | AMBOS | 1 |
| 16 | Insecure Deserialization | JSON estricto con schema Pydantic; sin `pickle`/`yaml.load` de entrada; eventos validados contra schema versionado | SVC | 1 |
| 17 | Software Supply Chain | SBOM + secret-scan + CVE con umbral en CI (§1.7) | CI | 1 |

> **Estado de verificación**: la matriz anterior es un **objetivo de diseño alineado a ASVS L2**. No existe aún evidencia de cobertura completa ni auditoría externa → verificación `PENDIENTE`; pen-test externo → `REQUIERE PROVEEDOR` (`W-build-now.md`, sección "No construible ahora").

---

## 3. Autenticación y sesiones

### 3.1 Passwords — Argon2id

| Parámetro | Valor recomendado (Fase 1) | Nota |
|---|---|---|
| Algoritmo | **Argon2id** (único permitido; prohibido MD5/SHA-1/SHA-256 puro/bcrypt/plaintext) | `00-decisions.md` §7 |
| Memoria `m` | 65536 KiB (64 MiB) | RFC 9106 (recomendación de 2ª opción, ajustada); medible en CI |
| Iteraciones `t` | 3 | — |
| Paralelismo `p` | 4 | Ajustar si el benchmark de latencia de login lo exige |
| Sal | Aleatoria de 16 bytes por hash, almacenada en el hash | — |
| Pepper | Valor corto en secreto de entorno (no en DB, no en repo); rotación `PENDIENTE` | `REQUIERE PROVEEDOR` en prod (Vault/KMS) |
| Formato | `argon2id$v=19$m=65536,t=3,p=4$<sal>$<hash>` (autocontenido para migración de parámetros) | Rehash automático en login si cambian parámetros |
| Parámetro de coste | Debe completarse en <200 ms en el hardware de prod; verificado con benchmark antes de fijar | Si no cumple → ajustar y re-documentar |
| Mínimo de password | ≥12 caracteres, sin listas de comunes, sin reglas que fueren derivables; verificación opcional de breach-list `PENDIENTE` | Validación en servidor, no solo cliente |

### 3.2 Tokens y sesiones

| Elemento | Regla | Ubicación |
|---|---|---|
| Access JWT | **≤ 15 min** (`exp` real, no renovado por refresh silencioso); claims mínimos: `sub`, `sid`, `jti`, `iss`, `aud`, `iat`, `exp`, `scope[]`, `roles[]`, `mode`; nunca claim de privilegio editable por cliente | `identity` emite · `gateway` valida (JWKS) |
| Algoritmo JWT | Uno solo, declarado en config; rechazo explícito de `none` y de `alg` distinto al configurado. Elección EdDSA vs RS256 → `DECIDIR` en ADR (no se fija proveedor/clave aquí) | `gateway` + `identity` |
| Refresh token | Opaco, aleatorio ≥256 bits, **rotativo**: cada uso emite uno nuevo; TTL deslizante corto (definir por ADR, sugerido 30–90 d) con detección de inactividad | `identity` |
| Rotación y reuso | Cada refresh pertenece a una **familia** (`family_id`); detección de uso de un token ya rotado ⇒ invalidación inmediata de la familia completa + revocación de la sesión + evento de seguridad + notificación al usuario | `identity` + Redis |
| Revocación | Denylist en Redis por `jti`/`sid` con TTL = tiempo restante del token; latencia objetivo <5 s (`Q-api-map` §1.7.6) | `gateway` consulta denylist; `identity` escribe |
| Almacenamiento cliente | Refresh en cookie `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth` (scope mínimo); access en memoria de JS. **Prohibido** `localStorage` para refresh | `gateway` set-cookie · `apps/web` |
| Sesión | `session_id` UUIDv7 en DB (`identity.sessions`): `created_at`, `last_seen_at`, `ip_hash`, `user_agent` truncado, `device_id`, `revoked_at`, `mfa_state` | `identity` |
| Session fixation | Nuevo `session_id` y nuevo refresh en cada login; jamás reutilizar identificador entregado antes de autenticar | `identity` |
| Logout | `/auth/logout` revoca sesión actual; `/auth/logout-all` con step-up MFA revoca todas (ambas auditable y con respuesta idempotente) | `identity` + Redis |

### 3.3 MFA TOTP (tras feature flag)

| Regla | Detalle |
|---|---|
| Flag | `mfa_totp_enabled` (Fase 1, opt-in); activación obligatoria solo cuando se declare en ADR (no se impone aquí) |
| Estándar | TOTP RFC 6238, 6 dígitos, ventana ±1, secreto cifrado en reposo, `otpauth://` en enrolamiento |
| Verificación | Un solo uso del código (nonce en Redis con TTL corto); fallos → contador y lock (§3.5) |
| Códigos de respaldo | Generados en enrolamiento, hash de un solo uso, mostrados una sola vez, cantidad y revocación registrados |
| Step-up | Requerido en: cambio de password, alta/baja de MFA, creación/rotación/revocación de API keys, `logout-all`, acciones admin de efecto (coherente con `Q-api-map` §1.7.5) |
| Recuperación | Códigos de respaldo únicos; recuperación por soporte con verificación documental → `PENDIENTE` y **no** automatizada en Fase 1 |
| Passkeys/WebAuthn | `PENDIENTE` (`00-decisions.md` §7) |

### 3.4 Rate limit deslizante (Redis)

| Regla | Detalle |
|---|---|
| Algoritmo | Sliding window (contador por ventana deslizante o slide con log de timestamps); **no** fixed window simple en rutas de auth |
| Claves | `rl:{scope}:{dimension}:{id}` con TTL = ventana; dimensiones: IP, token/`sub`, ruta, par (IP+ruta), cuenta |
| Defaults | Coherentes con `Q-api-map.md` §5: login 10/min por IP y 5/min por cuenta; global 1000/min por IP; lectura 600/min por token |
| Respuesta | `429` + `Retry-After` + `RateLimit-Limit/Remaining/Reset` + `problem+json` `RATE_LIMITED` |
| Degradación | Si Redis cae: **fail-closed** en rutas `auth/*` (rechazo 503 con `Retry-After`), fail-open documentado solo en lecturas (riesgo aceptado y auditado) |
| Refuerzo | Segundo contador en el servicio para rutas financieras (defensa si el edge es bypaseado) |

### 3.5 Bloqueo de cuenta y backoff

| Umbrales (Fase 1, config por entorno) | Comportamiento |
|---|---|
| 5 fallos en 15 min | Backoff exponencial: espera `2^n` s con tope (sugerido 60 s) antes de procesar nuevo intento |
| 10 fallos en 15 min (por IP) | Bloqueo temporal de la IP en rutas de auth + evento de seguridad |
| 20 fallos en 15 min (por cuenta) | Bloqueo temporal de la cuenta; respuesta **genérica** (idéntica a login válido en tiempo) para no revelar estado |
| Éxito limpio | Resetea contadores; reset manual solo por soporte con auditoría |
| Lockout largo / manual | Cierre de cuenta por fuerza bruta persistente → evento + alerta; desbloqueo requiere rol `support`+`checker` (F7) o self-service con MFA |
| Coherencia | Umbrales alineados a `Q-api-map.md` §5 (`backoff` tras 5 fallos, bloqueo a 20/15 min) |

### 3.6 Dispositivos de confianza y login history

- **Dispositivos**: `identity.devices` con `device_id` (hash de huella del cliente: UA + características, sin fingerprint invasivo ni cross-site), `first_seen`, `last_seen`, `trusted_until`, `revoked_at`. "Olvidar dispositivo" fuerza re-login/re-MFA. La huella **no** se usa para tracking de terceros ni se comparte (minimización).
- **Login history**: tabla append-only en `identity` con `occurred_at` (UTC), `user_id`, `outcome` (`success/failed/mfa_required/locked`), `ip_hash` (HMAC con secreto de entorno; **no** IP en claro salvo necesidad de seguridad demostrada), `user_agent` truncado, `country` derivado de IP solo si aporte a seguridad (`PENDIENTE` de decisión), `correlation_id`. Visible para el propio usuario (`GET /auth/login-history`) y para `support`/`compliance` con auditoría.
- **Alertas**: email/push ante login desde dispositivo nuevo o cambio de MFA → adapters `notification` (`MOCK` en Fase 1).

---

## 4. Autorización

### 4.1 Modelo: RBAC + scope, denegación por defecto

| Capa | Regla |
|---|---|
| Gateway | Valida JWT/API key, `exp`, denylist y **scope mínimo de la ruta** (`read`/`trade`/`payments`/`admin`); devuelve `403 INSUFFICIENT_SCOPE` |
| Servicio | Evalúa **rol** y **pertenencia del recurso**; nunca confía solo en el gateway (Q §3.1) |
| Defaults | Sin rol → sin permisos; sin scope → sin ruta; permiso nuevo requiere migración + PR + auditoría |
| Denegación explícita | Las denegaciones se registran en debug/audit; los 403/404 de autorización no filtran existencia de recursos ajenos |

### 4.2 Catálogo de roles (Fase 1 base; backoffice F7)

> **Nota de coherencia**: `Q-api-map.md` §1.7.4 cita un conjunto abreviado (`user`, `ops`, `compliance`, `auditor`, `superadmin`). El catálogo siguiente es el **objetivo de diseño completo** para este documento; reconciliar Q cuando los roles se implementen (`PENDIENTE` de actualización de Q).

| Rol | Propósito | Alcance típico | Hereda |
|---|---|---|---|
| `user` | Cliente final | Recursos propios: perfil, sesiones, API keys propias, cuentas propias | — |
| `support` | Atención al cliente | Lectura enmascarada de identidad y estado; nunca mueve dinero ni aprueba KYC | `user` |
| `compliance` | Cumplimiento/AML | Lectura ampliada + casos y alertas; export de auditoría con 4-ojos | `support` |
| `kyc-analyst` | Revisión KYC | Aprobar/rechazar casos KYC con motivo (4-ojos); sin acceso a ledger ni retiros | `support` |
| `risk-operator` | Operación de riesgo | Límites, kill switches, circuit breakers; **no** ejecuta órdenes ni aprueba pagos | `support` |
| `maker` | Proponente en flujos de 4-ojos | Crea la acción (retiro, cambio de límite, aprobación inicial) pero **no** puede aprobarla | `support` |
| `checker` | Aprobador en flujos de 4-ojos | Aprueba/rechaza acciones propuestas por otro usuario distinto; nunca el mismo `subject` que el `maker` | `compliance` |
| `admin` | Backoffice | Acciones sobre terceros con alcance de recurso; **sin** gestión de roles de nivel superior | `checker` |
| `superadmin` | Plataforma | Gestión de identidades, roles y flags; sin acceso a fondos; cambios inmutables (`live_trading`) vía 4-ojos | `admin` |

### 4.3 Reglas

1. **Mínimo privilegio**: cada ruta declara rol + scope mínimo; los permisos se otorgan por rol, nunca por usuario directo (excepción auditable y temporal).
2. **Denegación por defecto**: toda ruta nueva nace `deny`; el permiso se agrega en la misma PR con test.
3. **Separación de duties (maker-checker)**: aplicable a retiros, aprobaciones KYC, export de auditoría, cambios de flag, cambios de límite y altas de rol. Regla dura: `maker ≠ checker` en el mismo `subject_id`; registrado en `audit` con ambos actores (`actor_id` y `approver_id`).
4. **Step-up MFA** para toda acción de efecto (§3.3).
5. **Nunca por claim editable**: los roles viven en DB y se re-emiten en el JWT con `iat`; la revocación de rol fuerza refresh/revocación de sesión.
6. **Tests negativos obligatorios**: para cada endpoint, caso `403/404` por rol sin permiso y por recurso ajeno, en CI.

### 4.4 Criterios de paso a ABAC

Se migra de RBAC a ABAC (o RBAC + atributos) **solo** cuando concurra alguna evidencia medible:

| Criterio | Señal medible |
|---|---|
| Atributos de contexto | Necesidad de decisiones por jurisdicción, `mode` (DEMO/LIVE), tier KYC, instrumento o monto simultáneamente |
| Matriz de permisos | >30 permisos condicionales o >20 roles con solapamiento difícil de auditar |
| Cambios frecuentes | Varias decisiones de acceso por semana que RBAC resuelve con roles ad-hoc acumulados |
| Auditoría | Dificultad para responder "¿por qué X pudo hacer Y?" en menos de un minuto |

Migración: motor de decisiones centralizado (`opa`/`casbin` u otra opción OSS → **elección por ADR**, sin fijar proveedor aquí), políticas versionadas como código, shadow mode (log de decisiones) antes de enforcement, rollback por flag. Estado: `PENDIENTE` (Fase 7, junto al RBAC fino de `Q-api-map` §6).

---

## 5. Criptografía y secretos

| Área | Regla | Estado |
|---|---|---|
| Transporte externo | TLS 1.2+ (preferir 1.3) en todo `/api/v1`; HTTP redirigido a HTTPS; sin contenido mixto | `PENDIENTE` (requiere `[DOMAIN]` real) |
| HSTS | `Strict-Transport-Security: max-age=31536000; includeSubDomains` tras verificar dominio real; `preload` solo con decisión explícita y dominio definitivo | `PENDIENTE` |
| TLS interno (compose) | Tráfico entre gateway y servicios en red Docker interna (sin exposición pública); TLS/mutuo **PENDIENTE** | `PARCIAL` (red aislada) / `PENDIENTE` |
| mTLS en Kubernetes | Certificados por servicio con rotación automatizada; no se selecciona CA/proveedor en este documento | `PENDIENTE` (Fase K8s) |
| Cifrado en reposo (PG) | Volumen cifrado en infraestructura de producto → `REQUIERE PROVEEDOR` (cloud/KMS). En local: cifrado del disco del host, no del volumen → declarado | `REQUIERE PROVEEDOR` / `PENDIENTE` |
| Cifrado de campos | PII sensible y secretos (TOTP seed, tokens) cifrados a nivel de campo (AES-256-GCM) con clave por entorno; clave en KMS/Vault → `REQUIERE PROVEEDOR` en prod; en local en `.env` no versionado | `PENDIENTE` |
| Hash de identificación | Contraseñas Argon2id (§3.1); API keys: hash del secreto completo (KDF) + prefijo público no secreto para listar; **jamás** el secreto completo almacenado ni logueado | `PENDIENTE` |
| Secretos por entorno | Local: `.env` (gitignored) con `.env.example` sin valores. CI: GitHub Secrets. Producción: **Vault/KMS `REQUIERE PROVEEDOR`** — no se elige producto aquí | `PENDIENTE` / `REQUIERE PROVEEDOR` |
| Rotación | Secretos de servicio con rotación programada y verificación de caducidad en CI; JWT con rotación de claves vía JWKS (`kid`), solapamiento de claves vieja+nueva durante la ventana de validación | `PENDIENTE` |
| Jamás secretos en… | repo · logs · trazas OTel · frontend (bundle Next.js) · respuestas de API · eventos de Redpanda · documentos de este repo · screenshots de runbooks | Invariante (`00-decisions.md` §7) |
| Detección | Secret-scan bloqueante en CI sobre todo el historial (BUILD-005); rotación inmediata si se detecta fuga | `PENDIENTE` |
| Gestión de claves | Inventario de secretos (qué, dueño, rotación, TTL) → tabla en runbook `PENDIENTE`; sin HSM ni KMS elegidos en Fase 1 | `PENDIENTE` |

---

## 6. Cabeceras de seguridad

Todas se inyectan en **un único punto**: middleware de respuesta del `gateway` (última capa antes del cliente). Los servicios no las emiten al exterior; sí emiten `Cache-Control: no-store` interno cuando el gateway los reenvía.

| Cabecera | Valor Fase 1 | Propósito |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'nonce-{uuid}'; style-src 'self' 'nonce-{uuid}'; img-src 'self' data:; font-src 'self'; connect-src 'self' wss://{[DOMAIN]}; upgrade-insecure-requests` | Anti-XSS; nonce por request para scripts/styles de Next.js (`nonce` en `<Script>`); sin CDNs de terceros |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (solo tras dominio real y HTTPS verificado; sin `preload` automático) | Fuerza HTTPS |
| `X-Content-Type-Options` | `nosniff` | Evita MIME sniffing |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Evita fuga de URLs |
| `Permissions-Policy` | `geolocation=(), camera=(), microphone=(), payment=(), usb=(), interest-cohort=()` | Minimización de sensores del cliente |
| `X-Frame-Options` | `DENY` (compatibilidad; CSP `frame-ancestors` es la norma moderna) | Anti-clickjacking |
| `Cross-Origin-Opener-Policy` | `same-origin` | Aísla el browsing context |
| `Cross-Origin-Resource-Policy` | `same-site` | Limita recursos cross-origin |
| `Cache-Control` | `no-store` en `/api/v1/auth/*`, `/api/v1/me`, datos personales; `no-store` por defecto en respuestas con PII | Evita caché/disco |
| Cookies (refresh y sesión) | `Secure; HttpOnly; SameSite=Lax; Path=/api/v1/auth; Domain` mínimo necesario | Robo/CSRF de cookies |
| Cookies (CSRF, si aplica) | `SameSite=Strict` (o `Lax`) + lectura solo por script propio | Doble submit |

**Orden sugerido del middleware del gateway**: (1) request-id/correlation-id → (2) trusted proxy check → (3) rate limit → (4) auth (JWT/API key + denylist) → (5) route allowlist/`/internal` block → (6) body limit → (7) proxy a servicio → (8) cabeceras de seguridad + `RateLimit-*` → (9) log/trace. **Estado**: `PENDIENTE`.

**Nota**: sin `[DOMAIN]` definido no se emiten HSTS con `preload` ni CSP con dominios externos reales (`00-decisions.md` §1).

---

## 7. Seguridad entre servicios

| Capa | Regla Fase 1 (compose local) | Regla objetivo (K8s) | Estado |
|---|---|---|---|
| Red | Red Docker interna; solo `gateway` publica puerto; servicios sin puertos host | NetworkPolicies de default-deny + permit por par (origen, destino) | `PENDIENTE` |
| Transporte | HTTP dentro de la red del compose (aislamiento por red) | **mTLS** con certificados por servicio y rotación automatizada | `PARCIAL` / `PENDIENTE` (K8s) |
| Identidad de servicio | JWT de servicio firmado por `identity`: TTL **≤5 min**, `iss=platform-internal`, `sub=svc:<nombre>`, `scope=svc:<nombre>`; **no** hereda scopes de usuario | igual + mTLS | `PENDIENTE` |
| Rutas internas | `/internal/v1/*` jamás enrutadas por el gateway (404) y solo en red de servicio | igual + mTLS | `PENDIENTE` |
| Propagación de usuario | `x-user-id`/`x-on-behalf-of` en JWT corto con claim `act`; **prohibido** propagar cookies o refresh tokens | igual | `PENDIENTE` |
| Trazabilidad | `x-request-id` y `x-correlation-id` obligatorios en cada hop | igual | `PENDIENTE` |
| Idempotencia | `Idempotency-Key` en toda mutación financiera interna | igual | `PENDIENTE` |
| Cuotas internas | Cuota por par (origen, destino) + circuit breaker + timeouts cortos; sin malla de servicios en Fase 1 | malla `PENDIENTE` | `PENDIENTE` |
| Revalidación | El servicio destino revalida pertenencia/scope (no confía ciegamente en el edge) | igual | `PENDIENTE` |
| Eventos | Preferencia por Redpanda/outbox; el síncrono solo cuando se necesita respuesta inmediata | igual | `PENDIENTE` |
| Datos sensibles en eventos | Prohibido publicar passwords, hashes, API key secrets, refresh tokens o PII completa en eventos | igual | Invariante |

---

## 8. Seguridad de APIs

### 8.1 Rate limit y quotas

| Dimensión | Aplicación | Detalle |
|---|---|---|
| Por IP | Gateway | Sliding window; 1000/min global; 10/min en `auth/login`; bloqueo temporal de IP ante abuso |
| Por usuario/token | Gateway + refuerzo en servicio | 600/min lectura; 120/min trading; 30/min escritura identidad |
| Por ruta | Gateway | Límites declarados en `openapi.yaml` (`x-rate-limit`) y en `Q-api-map.md` §5 |
| Por cuenta/empresa | Servicio (cuota de negocio) | Retiros/día, jobs de export/hora, órdenes abiertas → `429 QUOTA_EXCEEDED` |
| Headers | Gateway | `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `Retry-After` |

### 8.2 API keys

| Aspecto | Regla |
|---|---|
| Scopes | `read`, `trade`, `payments`, `admin` (fino por recurso → `PENDIENTE` F7). La creación **nunca** amplía a `admin` por defecto; scope se declara explícitamente |
| Creación | Solo con sesión de usuario + step-up MFA; con `expires_at` obligatorio (sugerido ≤1 año) y `scopes[]` mínimos |
| Almacenamiento del secreto | Prefijo público no secreto (p. ej. `pk_<id>_<4 chars>`) para identificación + **hash KDF del secreto completo** en DB. El secreto completo se muestra **una sola vez** en la respuesta de creación y **no** vuelve a exponerse en listados ni logs |
| Listado | Solo prefijo / últimos 4 + metadata (scopes, expiración, último uso, IP allowlist) |
| IP allowlist | Campo opcional `ip_whitelist[]`; si está presente, el gateway rechaza con `403` cualquier llamada desde IP distinta |
| Expiración | `expires_at` obligatorio; expirada → `401` con código tipado; recordatorio antes de vencer `PENDIENTE` |
| Rotación | `PATCH /api-keys/{id}` con rotación de secreto: ventana de solape configurable (sugerido ≤24 h) emitiendo secreto nuevo; revocación del viejo al final |
| Revocación | `DELETE /api-keys/{id}` con efecto **inmediato** en gateway (cache de introspección con TTL ≤60 s + invalidación explícita) |
| Uso | Último uso y contador de errores registrados; anomalías (país/IP nuevo, salto de volumen) → evento de seguridad |
| Sandbox vs LIVE | Keys sandbox jamás alcanzan rutas LIVE (BUILD-052); separación por prefijo + `mode` en el token |

### 8.3 Otras defensas de API

- **Anti-enumeración**: mensajes idénticos para recurso inexistente y no autorizado (`404`), y respuestas genéricas en auth.
- **Idempotencia**: `Idempotency-Key` obligatorio en toda mutación financiera (Q §1.8) — también mitiga replay.
- **Límites de payload**: 1 MiB escritura / 8 MiB KYC → `413`.
- **Validación estricta**: Pydantic `extra="forbid"`; desconocido → `422 VALIDATION_ERROR`.
- **Versionado**: `/api/v1` + diff de OpenAPI en CI para impedir apertura accidental de superficie.

---

## 9. Eventos de seguridad a registrar

Destino: `services/audit` (append-only, consumidor de eventos) vía **transactional outbox** → Redpanda. Todo evento lleva `event_id`, `event_type`, `schema_version`, `timestamp` UTC, `correlation_id`, `request_id`, `session_id` (cuando aplique), `actor_id`, `ip_hash`, `mode` (coherente con `00-decisions.md` §8 y `P-event-catalog.md`).

| # | Evento | Datos mínimos | Severidad típica |
|---|---|---|---|
| 1 | `auth.login.succeeded` | actor, sesión, device, ip_hash | INFO |
| 2 | `auth.login.failed` | motivo tipado (bad_password/mfa), intento #, ip_hash | WARN |
| 3 | `auth.login.locked` | cuenta/IP, ventana, umbrales | ALERTA |
| 4 | `auth.password.reset.requested` / `.confirmed` | actor, ip_hash, canal | WARN |
| 5 | `auth.password.changed` | actor, método, sesiones revocadas | INFO |
| 6 | `auth.mfa.activated` / `.deactivated` / `.recovery_used` | actor, método, operador si es admin | ALERTA |
| 7 | `auth.session.revoked` / `.revoked_all` | actor, alcance, motivo | INFO/WARN |
| 8 | `auth.refresh.rotated` / `auth.refresh.reuse_detected` | familia, sid; el reuso es **ALERTA** y revoca familia | ALERTA |
| 9 | `apikey.created` / `.rotated` / `.revoked` | actor, scopes, prefijo, ip_allowlist (nunca el secreto) | ALERTA |
| 10 | `role.granted` / `.revoked` | actor, sujeto, rol, motivo | ALERTA |
| 11 | `permission.denied` | actor, recurso, rol, ruta (muestreo para no inundar) | WARN |
| 12 | `admin.action.*` (backoffice) | actor, target, acción, resultado, approver_id | ALERTA |
| 13 | `maker_checker.proposed` / `.approved` / `.rejected` | maker, checker, objeto, motivo | ALERTA |
| 14 | `flag.changed` | actor, clave, valor previo→nuevo; `live_trading` **inmutable** | ALERTA |
| 15 | `webhook.signature.failed` / `.rate_limited` | proveedor, ip_hash | WARN |
| 16 | `security.export.requested` (auditoría/reportes) | actor, rango, aprobador | ALERTA |

### Política de no-logging (obligatoria)

| Regla | Detalle |
|---|---|
| Nunca registrar | passwords (claros o form data), hashes, pepper, JWT/refresh tokens, API key secrets, TOTP seeds/códigos, cookies, `Authorization`, claves privadas, connection strings |
| PII minimizada | Emails e IP **hasheados** por defecto en logs y trazas; PII completa solo en DB de `identity` con acceso restringido y cifrado de campo |
| Redacción | Logger con redactor de campos sensibles (`password`, `token`, `secret`, `authorization`, `cookie`, `otp`); middleware de acceso que sanea query/body de rutas auth |
| Trazas OTel | Atributos permitidos por allowlist; sin body de request en spans; sin PII en `resource.attributes` |
| Retención | Logs/audit: retención por clase definida en `O-database-strategy.md` → **duración concreta `DECIDIR`** con insumo legal (`REQUIERE LICENCIA/REGULACIÓN`); eventos en DLQ sin PII |
| Auditoría | `audit` es append-only e inmutable: sin UPDATE/DELETE, hash encadenado, verificación periódica de integridad (`PENDIENTE`) |
| Acceso a logs | Solo roles operativos con auditoría; export de audit exige 4-ojos |

---

## 10. Threat model STRIDE (resumido)

| Escenario | S | T | R | I | D | A | Mitigación concreta | Ubicación | Estado |
|---|---|---|---|---|---|---|---|---|---|
| **Account takeover** (credential stuffing, session hijack, phishing) | ✓ | ✓ | ✓ | ✓ | | ✓ | Argon2id + rate limit por IP/cuenta + backoff/lock + MFA TOTP (flag) + JWT ≤15 min + refresh rotativo con detección de reuso + denylist <5 s + cookies HttpOnly/SameSite + login history + alerta de device nuevo | gateway + `identity` | `PENDIENTE` |
| **Fraude en retiros** (cuenta comprometida o insider) | ✓ | ✓ | | ✓ | | ✓ | Step-up MFA + allowlist/confirmación de destino + maker-checker + cuotas diarias + hold/4-ojos + auditoría con `correlation_id` + notificación al titular | `payments`/`admin` + `identity` | `PENDIENTE` (F6/F7) |
| **Pago fraudulento / webhook falsificado** | ✓ | ✓ | | ✓ | ✓ | | Firma HMAC con comparación en tiempo constante + ventana temporal + IP allowlist del proveedor + `Idempotency-Key` + adapter desacoplado + rechazo sin JWT | `payments` (F6) | `PENDIENTE` (F6) |
| **Abuso de API / bots** (scraping, brute force, stuffing) | ✓ | ✓ | | ✓ | | | Sliding window IP/token/ruta + quotas de negocio + API keys con scopes/IP allowlist/expiración + límite de rango de consulta + uniformidad de errores | gateway + servicios | `PENDIENTE` |
| **Insider threat** (operador con privilegios) | | ✓ | ✓ | ✓ | ✓ | ✓ | Mínimo privilegio + maker-checker + PII enmascarada por defecto en backoffice + audit append-only + sin acceso directo a DB entre servicios + alertas en acciones admin + sin credenciales compartidas | RBAC + `audit` | `PENDIENTE` |
| **Escalada de privilegios** (masa assignment, JWT forjado, rol manipulado) | ✓ | ✓ | ✓ | ✓ | | ✓ | Roles solo en DB con migración + auditoría; Pydantic `extra="forbid"`; verificación JWKS con `alg` fijo; denegación por defecto + tests negativos por rol; step-up MFA para cambios sensibles | `identity` + gateway | `PENDIENTE` |
| **Tampering de ledger** (modificar saldos/asientos) | | ✓ | | ✓ | ✓ | ✓ | Append-only + `REVOKE UPDATE/DELETE` + constraints de balance cero + hash encadenado + reconciliador ledger↔wallet + postings solo vía `/internal/v1/postings` + outbox pareado | `ledger` (F2) | `PENDIENTE` (F2) |
| **Manipulación de market data** (feed falso, replay) | ✓ | ✓ | | ✓ | ✓ | | Adapters con contrato + validación de banda/rango + etiqueta `simulated` + detección de huecos + source y timestamp en cada tick + kill switch auditable | `market-data`/`risk` (F3/F4) | `PENDIENTE` (F3/F4) |
| **DDoS** (volumen, aplicación, WS) | ✓ | ✓ | | ✓ | | ✓ | Rate limit por IP global + por ruta + límite de cuerpo + cuotas WS (5/usuario) + timeouts + circuit breakers + fail-open documentado solo en lectura + capacidad de escalar `PENDIENTE` (proveedor anti-DDoS no elegido) | gateway + infra | `PARCIAL` diseño / `REQUIERE PROVEEDOR` (edge anti-DDoS) |
| **Supply chain** (paquete/imagen/action comprometida) | ✓ | ✓ | ✓ | ✓ | ✓ | | Lockfiles + pin por digest/SHA + SBOM + secret-scan + umbral de CVE en CI + registry oficial + revisiones de dependencias | CI | `PENDIENTE` |

**Riesgos residuales declarados**: (1) sin proveedor anti-DDoS y sin WAF → el edge de aplicación es la única barrera; (2) cifrado en reposo dependiente de infraestructura no elegida; (3) sin pen-test externo; (4) sin segmentación de red real hasta K8s; (5) secretos locales en `.env` dependen de la higiene del puesto de desarrollo. Todos → `REQUIERE PROVEEDOR` / `PENDIENTE` y se reevalúan antes de LIVE (§11).

---

## 11. Checklist / gate de seguridad antes de cualquier entorno LIVE

> **Etiqueta global**: cualquier activación de `live_trading` o de dinero real es **`REQUIERE LICENCIA/REGULACIÓN`** (`00-decisions.md` §6, `W-build-now.md`, `X-blocked-to-live.md`). Este gate es **necesario pero no suficiente**; la activación final exige además aprobación legal, contratos con proveedores y evidencia documentada. El flag `live_trading=false` es **inmutable** hasta completar todos los puntos.

### 11.1 Gate técnico (bloqueante)

- [ ] `live_trading=false` verificado en config y con test que impide su activación sin el gate.
- [ ] Argon2id activo como único mecanismo de password; sin hashes débiles en DB; benchmark de coste documentado.
- [ ] JWT ≤15 min + refresh rotativo con **test de reuso** que invalida familia; denylist con latencia <5 s medida.
- [ ] MFA TOTP disponible tras flag con códigos de respaldo y step-up en rutas sensibles (o excepción aprobada por escrito).
- [ ] Rate limit deslizante activo por IP/token/ruta con fail-closed en `auth/*`; headers `RateLimit-*` presentes.
- [ ] Todas las cabeceras §6 emitidas por el gateway; CSP sin `'unsafe-inline'`/`'unsafe-eval'` salvo excepción justificada y con nonce.
- [ ] Cookies `Secure; HttpOnly; SameSite` verificadas en respuesta real.
- [ ] `/internal/*` responde `404` desde el edge (test automatizado).
- [ ] RBAC con denegación por defecto + **tests negativos por rol** y anti-BOLA (`404` uniforme) en CI.
- [ ] Maker-checker operativo en: retiros, KYC, export de auditoría, cambios de flag, altas de rol.
- [ ] API keys: hash del secreto, expiración, allowlist IP, rotación y revocación inmediata probadas.
- [ ] Idempotencia obligatoria en flujos financieros (sin duplicados en replay).
- [ ] Webhooks: verificación de firma + ventana temporal + IP allowlist + rechazo probado.
- [ ] Auditoría append-only con `correlation_id`/`request_id`, sin PII innecesaria, con verificación de integridad y sin posibilidad de UPDATE/DELETE.
- [ ] Política de no-logging aplicada y verificada (secret-scan de logs + test de redacción).
- [ ] CI: secret-scan, SBOM, umbral de CVE, lint de fronteras, tests, diff de OpenAPI — todos bloqueantes y en verde.
- [ ] Backups cifrados con **restore probado**; runbook de recuperación (`BUILD-062`) ejecutado al menos una vez.
- [ ] Gestión de incidentes: runbook de rotación de credenciales, de revocación masiva de sesiones y de kill switch.
- [ ] Pen-test / revisión de seguridad externa realizada con hallazgos críticos cerrados → `REQUIERE PROVEEDOR`.
- [ ] Inventario de secretos con dueños y caducidades; rotación automática demostrada → `REQUIERE PROVEEDOR` (Vault/KMS).

### 11.2 Gate legal / regulatorio (bloqueante, `REQUIERE LICENCIA/REGULACIÓN`)

- [ ] Licencia/autorización vigente para ofrecer el servicio y la clase de producto.
- [ ] Proveedores reales contratados: ejecución/market data, pagos, KYC/AML, comunicaciones → `REQUIERE PROVEEDOR`.
- [ ] KYC/AML real en producción con screening de sanciones y monitoreo → `REQUIERE PROVEEDOR`.
- [ ] Contratos, términos, política de privacidad, retención y derechos de usuario aprobados legalmente.
- [ ] Clasificación de datos, registro de tratamiento y evaluación de impacto de privacidad completados.
- [ ] Requisitos fiscales y de reporte regulatorio verificados por jurisdicción.
- [ ] Segregación DEMO/LIVE auditada: ningún dato simulado presentado como real; cuentas y ledgers separados.

### 11.3 Gate de datos / gobernanza (bloqueante)

- [ ] Owner/steward asignado por dataset; clasificación y sensibilidad documentadas.
- [ ] Retención y eliminación definidas y automatizadas (sin borrados manuales en producción).
- [ ] Cifrado en reposo activo con gestión de claves → `REQUIERE PROVEEDOR`.
- [ ] Permisos de DB por servicio verificados (sin acceso cruzado a schemas).
- [ ] Logs y trazas con minimización de PII y acceso restringido auditado.

---

## 12. Pendientes / No determinado

| Tema | Estado |
|---|---|
| Definición de `[DOMAIN]` (HSTS real, CSP con dominios, certificados) | `PENDIENTE` (`00-decisions.md` §1) |
| Algoritmo JWT (EdDSA vs RS256) y TTL exacto de refresh | `DECIDIR` en ADR |
| Vault/KMS, CA/mTLS, WAF, anti-DDoS, CDN, HSM | `REQUIERE PROVEEDOR` |
| Pen-test y auditoría de seguridad externa | `REQUIERE PROVEEDOR` |
| Certificación/cumplimiento (ASVS L2 verificado, PCI DSS, SOC 2, ISO 27001, regulatorio) | `REQUIERE LICENCIA/REGULACIÓN` — **no se afirma cumplimiento** |
| Passkeys/WebAuthn | `PENDIENTE` (`00-decisions.md` §7) |
| RBAC fino por recurso y motor ABAC | `PENDIENTE` (F7, `Q-api-map.md` §6) |
| Retención concreta de logs/audit por jurisdicción | `DECIDIR` con insumo legal |
| Cifrado en reposo en local (Docker Desktop/WSL) | `PENDIENTE` (depende del host) |
| Propagación de IP en claro para seguridad (vs `ip_hash`) | `DECIDIR` con criterio de minimización |
| Reconciliación de roles: este documento vs `Q-api-map.md` §1.7.4 | `PENDIENTE` de actualización de Q |
| Threat model detallado por flujos y runbooks asociados (`BUILD-062`) | `PENDIENTE` (Fase 1) |
| Bloqueo por geolocalización/jurisdicción en edge | `PENDIENTE` (F2 con matriz de jurisdicciones) |

---

*Fin del documento G-security-architecture.md*
