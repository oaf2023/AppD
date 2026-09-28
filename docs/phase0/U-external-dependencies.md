# U — Dependencias Externas (External Dependencies)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `[PROJECT_NAME]` · Dominio: `[DOMAIN]` · Marca: `[BRAND_NAME]`
Complementa: `00-decisions.md` §10 (regla de no-ficción), `T-roadmap.md` (gates externos G3/G6/G8/G9), `X-blocked-to-live.md`.

---

## 1. Alcance y reglas de lectura

1. **Ninguna fila de este documento implica que exista relación comercial, cuenta, credencial, contrato o licencia con alguien.** Estado real al 2026-09-27: **cero** proveedores contratados, **cero** credenciales emitidas, **cero** contratos firmados.
2. **Regla de no-ficción**: ante ausencia de proveedor no se inventa nada; se construye `interface + adapter + mock/sandbox + placeholder de configuración` y se documenta qué falta (`00-decisions.md` §10).
3. **Mitigación universal de acoplamiento**: toda dependencia externa se consume **solo** a través de un adapter propio en la frontera del dominio, con **failover** (segundo proveedor o degradación controlada), timeout, circuit breaker y modo mock para desarrollo. Ningún SDK/tipo de proveedor penetra en el núcleo (`trading`, `ledger`, `risk`, `accounts`).
4. **Definición de estados de la columna `Estado`**:

| Estado | Significado |
|---|---|
| `NO DISPONIBLE` | No hay proveedor identificado ni contratado, ni cuenta, ni credenciales, ni contrato, ni sandbox. **Es el estado real de todas las filas de este documento.** |
| `REQUIERE PROVEEDOR` | Categoría definida y adapter previsto; falta seleccionar y dar de alta al proveedor (cuenta + credenciales + sandbox). |
| `REQUIERE CONTRATO` | Proveedor identificado en fases posteriores; falta firma comercial/legal (SLA, DPA, costos, exit clause). |

5. **Columna `Fase bloqueada`**: primera fase cuyo *gate* no puede cerrarse sin que la dependencia pase a estado real. En las fases anteriores la dependencia existe como `MOCK`/`PENDIENTE` declarado (nunca presentado como real).

---

## 2. Tabla maestra de dependencias externas

> Categoría sin nombres de empresa (prohibido referenciar proveedores concretos en requisitos, tests ni código).

| # | Dependencia (categoría) | Para qué se necesita en el sistema | Impacto si falta (qué queda MOCK/PENDIENTE) | Criterios de selección | Riesgo de acoplamiento y mitigación | Estado | Fase bloqueada |
|---|---|---|---|---|---|---|---|
| 1 | Market data de mercados reales (forex/crypto/índices) | Precios en vivo (ticks/candles) para mark-to-market, triggers SL/TP, cálculo de margen/PnL, gráficas y referencia de precio del EMS | `market-data` opera con `SimulatedFeedAdapter` (ticks sintéticos etiquetados `simulated`); PnL, margen y disparos calculados sobre precio simulado; Fase 3 sin ejecutar | Cobertura de símbolos; latencia tick→cliente; SLA/uptime; calidad (gaps, spikes, stale); histórico; costos/overage; API (WS/REST/FIX); redundancia de carrier | Alto: feed monopólico y tipos de proveedor filtrándose al dominio → `MarketDataAdapter` + **mínimo 2 proveedores** + failover <500 ms + cache local + normalización canónica propia | `NO DISPONIBLE` | 3 |
| 2 | Datos históricos forex/futures **con derechos de redistribución** | Charting histórico en UI, backtesting, datasets para clientes; exige permiso contractual de retransmisión a usuarios finales | Histórico y backtesting sobre dataset sintético propio; la UI no puede mostrar datos de terceros; sin redistribución, ningún feed de terceros en página pública | Derechos de redistribución explícitos por contrato; profundidad histórica (≥5 años); integridad/ajustes; costos por símbolo; formato normalizable | Medio-alto: licencia cara y rígida → adapter de histórico + licencia con cláusula de salida + capa de normalización propia reutilizable | `NO DISPONIBLE` | 3 |
| 3 | Liquidez y ejecución (LP / venue / broker) | Ejecución LIVE real, cotizaciones firmes, profundidad, settlement de órdenes de clientes | **LIVE bloqueado**; EMS solo con `InternalDemoExecutionAdapter` (ejecución interna determinista); sin venue no hay fills reales ni reports de ejecución externos | Licencia/regulación del venue; conectividad (FIX 4.4/5.0, REST); calidad de fill/slippage; latencia; uptime; costos; capacidad de settlement; contraparte y crédito | Crítico: proveedor = puerta del dinero real → `ExecutionAdapter` + **multi-venue routing** + failover + kill switch + reconciliación independiente contra ledger | `NO DISPONIBLE` | 9 |
| 4 | Proveedor KYC / documentos / liveness | Verificación de identidad, OCR de documentos, selfie/liveness, decisión de onboarding | `kyc` con `MockKycAdapter` (decisión determinista de prueba, claramente simulada); alta de cuenta real bloqueada; tiers KYC en `PENDIENTE` | Cobertura de países/documentos; tasas de fraude/aprobación; latencia de decisión; SDK/webhooks; SLA; costos por chequeo; privacidad y retención de PII; certificaciones | Alto: onboarding entrelazado con el proveedor → `KycAdapter` + segundo proveedor + flujo manual de respaldo + normalización de resultados propietaria | `NO DISPONIBLE` | 6 |
| 5 | Screening sanciones / PEP | Screening en onboarding y monitoring continuo de clientes y contrapartes | `ScreeningAdapter` con listas locales de prueba; compliance real bloqueado; alertas falsas/no falsas no evaluables | Cobertura de listas (sanciones, PEP, adverse media); fuzzy matching ajustable; latencia; ongoing monitoring; exportabilidad de decisiones para auditoría; costos | Medio: cambio de algoritmo del proveedor altera decisiones → adapter + umbrales propios versionados + re-screening periódico independiente + auditoría de cada decisión | `NO DISPONIBLE` | 6 |
| 6 | Pasarela de pago fiat (tarjeta / banco / e-wallet / rails locales) | Depósitos y retiros en moneda fiat, 3-D Secure, devoluciones, conciliación | `payments` con `MockPspAdapter` (depósitos/retiros simulados asentados en ledger demo); dinero real bloqueado; conciliación real en `PENDIENTE` | Métodos soportados por jurisdicción; PCI-DSS; costos/fees; rolling reserve; chargeback handling; SLA de settlement; webhooks firmados; calidad de conciliación | Crítico: PSP en camino de dinero → `PaymentAdapter` por rail + **2 PSPs objetivo por rail** + failover + idempotencia de webhooks + conciliación diaria ledger↔PSP | `NO DISPONIBLE` | 6 |
| 7 | Rampa crypto on/off-ramp | Compra/venta de cripto con fiat y depósitos/retiros on-chain (redes soportadas) | `payments`/`wallet` sin rails on-chain; retiros de cripto en `PENDIENTE`; todo balance cripto solo interno | Soporte de redes/tokens; custodia vs. non-custodial; costos de red; tiempos de confirmación; compliance travel rule; geolocalización permitida; SLA | Alto: irreversibilidad on-chain → `CryptoRampAdapter` + double-check de dirección + límites por transacción + monitoring de red + modo lectura antes de escribir | `NO DISPONIBLE` | 6 |
| 8 | Proveedor de liquidez de stablecoins | Conversión stablecoin↔fiat y estabilización de balances en stablecoins con precio fiable | Conversiones estables simuladas; precio de stablecoin marcado como `simulated`; PnL de conversión no realista | Paridad mantenida y mecanismo de redeem; costos/spread; liquidez por tamaño; atestaciones de reserve; jurisdicción; contraparte | Alto: dependencia de paridad → adapter + precio de referencia propio con bandas + límite de exposición total por proveedor + kill switch de conversión | `NO DISPONIBLE` | 6 |
| 9 | Email transactional | Verificación de correo, reset de contraseña, MFA, notificaciones de cuenta/orden/pago, receipts | `notification` con transporte mock (archivo/console en local, sink en tests); sin entrega real; flujos de verificación no completables por correo real | Deliverability/SPF-DKIM-DMARC; plantillas y API; latencia de entrega; rate limits; costos por volumen; logs de eventos; retención | Medio: plantillas y tracking acoplados → `EmailAdapter` + proveedor secundario (fallback) + plantillas propias versionadas + cola con reintentos | `NO DISPONIBLE` | 6 |
| 10 | SMS | Alertas de seguridad, OTP, notificaciones transaccionales críticas | `notification` sin canal SMS; 2FA por SMS en `PENDIENTE`; usuarios sin alerta telefónica | Cobertura geográfica/operadores; entregabilidad; costos por SMS/país; A2P registration; API/webhooks; soporte de plantillas | Medio: costo y dependencia de operador → `SmsAdapter` + segundo operador + fallback a email/in-app + límite de envío por usuario | `NO DISPONIBLE` | 6 |
| 11 | Push (web push / móvil) | Notificaciones in-app/push de fills, margin call, alertas de cuenta | Canal no implementado fuera de in-app interno; preferencias de push en `PENDIENTE` | Soporte de canales; segmentación; costos; opt-in/permisos; analytics de entrega; cumplimiento de privacidad | Bajo-medio: plataforma controla permisos → `PushAdapter` + in-app siempre disponible como canal base | `NO DISPONIBLE` | 8 |
| 12 | Object storage S3-compatible | Documentos KYC, estados de cuenta, reportes, backups de artefactos, logs fríos | Fase 1: placeholder `REQUIERE PROVEEDOR` + adapter mock local; Fase 2: statements en mock local; sin storage duradero real no hay evidencia regulatoria | API S3-compatible (portabilidad); regiones/data residency; versionado; cifrado en reposo; lifecycle; costos; durabilidad; cumplimiento | Medio: lock-in de APIs propietarias → `ObjectStorageAdapter` sobre API S3 estándar + soporte multi-bucket + ensayo de migración periódico | `NO DISPONIBLE` | 6 |
| 13 | Cloud (cuenta y regiones) | Alojamiento de cómputo, K8s, bases de datos, almacenamiento, redes, HA multi-AZ y DR multi-región | Todo corre en local/docker-compose; manifiestos K8s/Terraform sin estado real de nube; no hay entorno de staging/producción | Data residency y jurisdicción; certificaciones; SLA y soporte enterprise; costos predecibles; ecosistema gestionado (PDB/DR); salida (egress) | Crítico: SPOF de infraestructura → Terraform abstracto + preferencia a servicios gestionados portables + plan de egres/exportación + objetivos de DR (RPO/RTO) desde diseño | `NO DISPONIBLE` | 8 |
| 14 | WAF / protección DDoS | Protección del edge, reglas antifraude, rate limiting perimetral, mitigación de volumen | `gateway` expuesto solo con rate limit propio; sin defensa de perímetro externa; sin mitigación de ataques volumétricos | Cobertura L3–L7; reglas gestionadas + custom; latencia añadida; modo transparente; costos; reporting; integración con edge existente | Medio: vencer por el edge → `EdgeProtection` configurable por entorno + capacidad de operar solo con rate limit propio (degradación documentada) | `NO DISPONIBLE` | 8 |
| 15 | SIEM | Ingesta de logs/auditoría para detección de incidentes, retención regulatoria, alertas 24×7 | Logs solo en Loki/Tempo locales con retención corta; detección de incidentes manual; sin evidencia externa inmutable | Normalización de eventos; retención (7 años regulatorio); correlación; alertas; costos de ingest; exportación sin lock-in; cumplimiento | Medio-alto: retención cara y propietaria → OpenTelemetry/Loki como fuente estándar + exportación a SIEM vía pipeline propio + reintentos con buffer | `NO DISPONIBLE` | 8 |
| 16 | CA / certificados TLS (producción) | Certificados de servidor TLS 1.3 para dominios públicos, mTLS interno si aplica | Certificados autofirmados/dev en local; sin TLS público válido no hay sitio ni API públicos | Automatización (ACME/renovación); cobertura de dominios/wildcard; histórico de revocación; cadena de confianza aceptada; costos | Bajo: estándar abierto → rotación automatizada + múltiples CAs posibles + monitoreo de vencimiento | `NO DISPONIBLE` | 8 |
| 17 | HSM / KMS / Vault (gestión de secretos y claves) | Custodia de secretos, claves de cifrado, rotación, firmas, claves de JWT/TOTP | Fase 1: secretos en `env` local (nunca en repo); sin KMS no hay rotación automática ni evidencia de custodia; cifrado por columna limitado | Módulos certificados (FIPS/HSM si exige jurisdicción); rotación; acceso con menor privilegio; auditoría de uso; integración con runtime; costos | Crítico: secretos = activo → `SecretProvider` interface + Vault/KMS intercambiables + cache de corta vida + break-glass documentado; cero secretos en repo/logs/docs | `NO DISPONIBLE` | 8 |
| 18 | Banco para cuentas segregadas (cuentas de cliente / safeguarding) | Custodia de fondos de clientes, depósitos/retiros bancarios, segregación contable, interesteller settlement | Ledger registra fondos sin contraparte bancaria real; segregación real bloqueada; conciliación banco↔ledger en `PENDIENTE` | Jurisdicción y licencia del banco; cuentas segregadas/safeguarding; API bancaria; costos; tiempos de transferencia; estabilidad; requisitos KYB | Crítico: dinero real bajo custodia → `BankingAdapter` + **cuenta bancaria de respaldo** + conciliación diaria + política de apertura multi-banco | `NO DISPONIBLE` | 6 |
| 19 | CRM / soporte (live chat) | Atención al usuario, tickets, chat en vivo, historial de contactos ligado a la cuenta | Soporte por canales externos manuales o in-app básico; sin tickets ni SLA de soporte en producto; `admin-support` limitado | Integración con identidad/usuario; SLA; canal en app sin fugas de PII; costos; exportación de datos; cumplimiento de retención | Medio: datos de soporte fuera del perímetro → `SupportAdapter` + identidad compartida mínima + sin PII sensible en chats + exportación periódica propia | `NO DISPONIBLE` | 7 |
| 20 | Analytics de producto | Embudos, retención, uso de funciones, medición de eventos de negocio (sin PII innecesario) | Métricas solo desde Prometheus/Redpanda internos; sin funnel de producto; paneles de crecimiento en `PENDIENTE` | Minimización de datos; anonimización; opt-out; auto-hospedaje vs. SaaS; costos; calidad del dato; cumplimiento GDPR/CCPA | Medio: PII filtrándose a terceros → `AnalyticsSink` propio con eventos anonimizados + allowlist de campos + DPA y sin cookies de terceros sin consentimiento | `NO DISPONIBLE` | 7 |
| 21 | Captcha / anti-bot | Protección de registro, login, recuperación de contraseña y formularios públicos contra automatización | Solo rate limit + device fingerprint propio; bots no mitigados en superficie pública; fraude de cuenta en `PENDIENTE` | Tasa de falsos positivos; accesibilidad; costos por verificación; privacidad (sin tracking oculto); rendimiento en el flujo | Medio: widget de terceros en página → `BotDefenseAdapter` + fallback propio (proof-of-work/rate limit) + no bloquear accesibilidad | `NO DISPONIBLE` | 6 |
| 22 | Verificación de teléfono (OTP por SMS/voz) | Validación de número en onboarding, retiros, cambios de seguridad | Verificación de teléfono simulada (código aceptado en mock); `identity` sin canal telefónico real | Entregabilidad por país; costos; latencia; anti-SIM-swap; fallback voz/WhatsApp si aplica; cumplimiento A2P | Medio: canal caro y geográfico → `PhoneVerificationAdapter` + segundo canal + reintento controlado + límite de intentos | `NO DISPONIBLE` | 6 |
| 23 | Proveedor de dominios y correo corporativo | Dominio público de la marca `[DOMAIN]`, correo transaccional de origen, subdominios por entorno | Todo con nombres locales/`localhost`; sin dominio propio no hay sitio público, TLS válido ni envíos con reputación | Propiedad y transferibilidad del dominio; DNS gestionado (API); correo corporativo; costos; disponibilidad | Bajo-medio: dominio = identidad → registrar a nombre de la organización + DNS con API + plan de transferencia documentado | `NO DISPONIBLE` | 6 |
| 24 | Monitores de uptime / status page | Supervisión externa de disponibilidad, SLOs, page a on-call, status page pública | Solo healthchecks internos y Grafana local; sin verificación externa ni status pública; on-call sin alerta externa | Puntos de verificación multi-región; frecuencia; integración con alerting; status page pública; costos | Bajo: verificación externa → monitores redundantes + healthchecks propios como fuente base + sin dependencia del monitor para descubrir fallos | `NO DISPONIBLE` | 8 |
| 25 | Firma de penetration test externa | Evidencia de seguridad para gates de producción y cumplimiento | Sin informe externo; el gate G8 no puede cerrar | Alcance (API, WS, infra, app); metodología; seguimiento de remediación; confidencialidad; costos | Bajo: servicio temporal → alcance contractual + informe propio + remediación interna | `NO DISPONIBLE` | 8 |
| 26 | Auditor de cumplimiento / certificación | Evidencia SOC2/ISO o equivalente y auditoría de programa AML/CTF | Sin certificación externa; evidencia interna incompleta para G8/G9 | Experiencia en FinTech; cobertura de controles; plazos; costo; aceptación regulatoria | Bajo: temporal → evidencia recolectada con instrumentación propia (no solo esfuerzo del auditor) | `NO DISPONIBLE` | 8 |
| 27 | Licencia / autorización regulatoria | Operar con dinero real, ofrecer derivados, custodiar fondos y reportar a autoridades | **`live_trading` permanece `false`**; toda operación confinada a `DEMO`; plataforma legalmente no operativa para clientes reales | Jurisdicción; alcance de la autorización; capital; requisitos de reporting; plazos; costo legal | Existencial (no técnico): gating de fase + feature flag + revisión legal por fase; sin licencia ni código LIVE se habilita | `NO DISPONIBLE` | 9 |

---

## 3. Credenciales y certificados que **nunca** se inventan

Regla absoluta: no se generan, escriben, simulan ni versionan valores que parezcan reales. Todo lo siguiente está en estado **`NO DISPONIBLE`** y solo existe como placeholder de configuración con clave presente y valor ausente (`*_FROM_ENV`, vacío o error temprano en arranque):

- **Claves de cuenta cloud** (access key / secret key / token de sesión de infraestructura): `NO DISPONIBLE`.
- **API keys de proveedores externos** (market data, KYC, screening, PSP, crypto ramp, email, SMS, push, analytics, captcha, SIEM, CRM): `NO DISPONIBLE`.
- **Certificados TLS y claves privadas de producción** (y claves de CA privadas si se usara una propia): `NO DISPONIBLE` (solo certificados autofirmados de desarrollo local, marcados como tales).
- **Firmas de webhook reales** (secretos de firma de PSP/venue/proveedores, y cualquier secreto de firma con valor aparentemente real): `NO DISPONIBLE` (en tests solo constantes de ejemplo claramente ficticias).
- **Credenciales de banco** (tokens de API bancaria, claves de cuentas segregadas, credenciales de terminal/IBAM): `NO DISPONIBLE`.
- **Credenciales de conectividad de ejecución** (FIX SessionID/SenderCompID/Password, tokens de venue, claves de LP): `NO DISPONIBLE`.
- **Semillas y claves de custodia crypto** (MPC/HSM/on-chain signer): `NO DISPONIBLE`; jamás en repo, logs, docs, imágenes Docker ni variables de entorno de ejemplo.
- **Secretos de plataforma de mensajería** (SMTP auth, SMS API token, web push VAPID/VAPID keys de producción): `NO DISPONIBLE`.
- **Tokens de servicio internos de terceros** (OIDC client secret, OAuth app secret): `NO DISPONIBLE`.

Verificación periódica obligatoria: grep de patrones de secretos en CI (pre-commit + scan de historia) y rotación vía `SecretProvider` cuando exista proveedor (Fase 8).

---

## 4. Dependencias que **NO** bloquean la Fase 1–2

**Ninguna.** Todo lo de Fase 1 (y el núcleo de Fase 2) es propio: monorepo, `gateway`, `identity`, `audit`, `accounts`, `wallet`, `ledger`, `market-data` simulado, `trading` demo, `risk` demo, `notification` con transporte mock, CI/CD, observabilidad y frontend PWA corren con Docker local sin ninguna cuenta externa.

| Dependencia externa típica en F1–F2 | Cómo se cubre sin proveedor | Declaración honesta |
|---|---|---|
| Object storage | Adapter mock local (filesystem) | `MOCK` / `REQUIERE PROVEEDOR` |
| Secrets manager | Variables de entorno en local (cero en repo) | `MOCK` / `REQUIERE PROVEEDOR` |
| Market data real | `SimulatedFeedAdapter` con ticks sintéticos | `MOCK` (datos etiquetados `simulated`) |
| Email/SMS/push | Transporte archivo/console/sink de tests | `MOCK` |
| Pasarela de pago, KYC, screening, banco | Adapters mock con flujos deterministas | `MOCK` / `PENDIENTE` |
| Cloud, WAF, SIEM, CA, KMS, uptime | Docker local + cert autofirmado + stack OTel local | `PENDIENTE` (Fase 8) |
| Ejecución/liquidez real | `InternalDemoExecutionAdapter` | `MOCK` + `REQUIERE LICENCIA/REGULACIÓN` |

**Condición**: cada mock debe ser identificable como tal en logs, payloads, UI y documentación; prohibido presentar cualquier fila de esta tabla como operativa.

---

## 5. Qué dependencias bloquean cada fase

| Fase | Dependencias externas requeridas para cerrar gate | Estado actual | Si siguen sin resolverse |
|---|---|---|---|
| **F0** — Discovery | Ninguna | — | Gate interno |
| **F1** — Foundation | Ninguna (todo propio; placeholders declarados para S3 y Vault/KMS) | `NO DISPONIBLE` (sin impacto) | Gate G1 cierra igual |
| **F2** — Account & Demo | Ninguna (feed simulado, S3 mock, email mock) | `NO DISPONIBLE` (sin impacto) | Gate G2 cierra igual |
| **F3** — Market Data Real | #1 market data en vivo, #2 histórico con redistribución de datos | `NO DISPONIBLE` | **G3 bloqueado**; F4 con datos reales también |
| **F4** — Trading demo avanzado | Ninguna nueva (usa mocks F2 y feed F3 si existe) | — | Gate G4 interno cierra con mocks |
| **F5** — API Ecosystem | Ninguna nueva (OIDC build-vs-buy = decisión interna) | — | Gate G5 interno |
| **F6** — Payments/KYC/Onboarding | #4 KYC, #5 screening, #6 PSP fiat, #7 rampa crypto, #8 liquidez stablecoins, #18 banco segregado, #9 email, #10 SMS, #22 verificación de teléfono, #21 captcha, #12 object storage, #23 dominio/correo | `NO DISPONIBLE` | **G6 bloqueado**; sin onboarding ni dinero real |
| **F7** — Backoffice/Support | #19 CRM/support, #20 analytics de producto | `NO DISPONIBLE` | Gate G7 parcial (herramientas internas sí disponibles) |
| **F8** — Production Hardening | #13 cloud, #14 WAF/DDoS, #15 SIEM, #16 CA TLS, #17 HSM/KMS/Vault, #24 uptime, #25 pen test, #26 auditor | `NO DISPONIBLE` | **G8 bloqueado**; sin producción pública duradera |
| **F9** — Live & Go-Live | #27 licencia regulatoria, #3 LP/venue/ejecución, #1 y #2 reconfirmados con contrato vigente, seguros y reporting (ver `T-roadmap.md` §9) | `NO DISPONIBLE` | **G9 bloqueado**; `live_trading=false` indefinidamente |

---

## 6. Proceso de selección (obligatorio antes de cambiar estado)

1. Necesidad real documentada → 2. descubrimiento de candidatos → 3. **documentación oficial vigente verificada** → 4. evaluación (seguridad, SLA, calidad, costo, rate limits, privacidad, mantenimiento, salida) → 5. sandbox/cuenta de prueba con credenciales reales → 6. contrato (SLA, DPA, costos, cláusula de salida, prohibición de uso de datos de clientes) → 7. adapter + failover implementados y probados → 8. registro con **fecha de última verificación**.

| Integración (categoría) | Adapter propio | Failover previsto | Última verificación | Estado |
|---|---|---|---|---|
| Todas las categorías de §2 | definidos en diseño | definidos en diseño | — (sin proveedor) | `NO DISPONIBLE` |

Detalle de integraciones externas con timeouts, retries, circuit breaker y fallbacks: `docs/phase0/Q-api-map.md` y skill `api-governance`.

---

*Fin del documento U-external-dependencies.md*
