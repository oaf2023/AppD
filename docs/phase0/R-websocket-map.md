# R — Mapa WebSocket `/ws/v1` (Streaming Map)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `[PROJECT_NAME]` · Dominio: `[DOMAIN]` · Marca: `[BRAND_NAME]`

> **Regla de lectura**: diseño objetivo, no afirmación de implementación. La columna **Fase** indica la fase planeada; el estado real por componente se declara en `W-build-now.md` y `X-blocked-to-live.md`. Complemento REST: `Q-api-map.md`. Eventos de negocio (numéricos de las tablas): `P-event-catalog.md`.

---

## 1. Alcance y Transporte

| Regla | Detalle |
|---|---|
| URL | `wss://<DOMAIN>/ws/v1` (TLS obligatorio; `ws://` solo en local) |
| Subprotocolo | `v1.platform.json` (frames JSON). Sin subprotocolo → cierre `4400` |
| Propietario del hub | Infraestructura de streaming servida desde `market-data` (Fase 3) como primer caso; los tópicos de negocio la consumen en fases posteriores. El gateway termina el upgrade y delega, manteniendo rate limit de conexiones y headers de trazabilidad |
| Relación con REST | REST es fuente de verdad para comandos y **backfill**; WS es solo difusión + suscripción. Ninguna mutación financiera se ejecuta por WS (solo ACK de suscripción) |
| Modo | Todo payload lleva `mode: "DEMO" | "LIVE"`; con `live_trading=false` no se publica ningún dato LIVE |

---

## 2. Handshake y Autenticación

### 2.1 Secuencia

```text
1. Cliente  → GET /ws/v1 (Upgrade: websocket)           [sin credenciales en el path largo]
2. Gateway  → 101 Switching Protocols                    [si pasa rate limit de conexiones + origin check]
3. Cliente  → {"type":"auth","ticket":"<uso-único>"}      [obligatorio en ≤5 s]
4. Server   → {"type":"auth.ok","connection_id":"…","user_id":"…","scopes":[…],"expires_at":"…"}
   |         → cierre 4401 si falta/falla (nunca se habla de tópicos sin autenticar)
5. Cliente  → subscribe/unsubscribe → ack con id
6. ping/pong + sequence por topic + adviso/backpressure
```

### 2.2 Mecanismos de credencial

| Mecanismo | Regla | Uso |
|---|---|---|
| **Preferido: ticket de un solo uso** | `POST /api/v1/auth/ws-tickets` (sesión/API key) devuelve `ticket` con TTL **30 s**, un solo consumo, ligado a `user_id` + `scopes` + `client_ip`; consumo en el primer frame `auth` | Todos los clientes |
| **Alternativa restringida: query** | `wss://…/ws/v1?ticket=<uso-único>` — **solo** el ticket (TTL ≤ 30 s), nunca un access token de 15 min en query string (queda en logs de proxies/CDN); si llega en query, se redacta de todos los logs | Navegadores que no puedan enviar el primer frame con fiabilidad |
| **Alternativa: token de acceso en primer frame** | `{"type":"auth","access_token":"<jwt ≤15 min>"}` — aceptado como fallback; se valida firma/exp/`aud`, igual que en REST | Clientes de prueba / SDK |
| Re-autenticación | El contexto de autenticación expira con el ticket/token; al expirar → `auth.expired` + cierre `4401` | Todos |
| Prohibido | Access token largo en query, credenciales en `Sec-WebSocket-Protocol` sin TLS, cookies de sesión como única autenticación, cualquier credencial en URL de redirección | — |

### 2.3 Autorización por topic (anti-BOLA)

| Regla | Detalle |
|---|---|
| Ownership en `subscribe` | Para `account:{id}`, `orders:{account}`, `positions:{account}`, `transactions:{account}`: el servidor verifica **en cada suscripción** que la cuenta pertenezca al `user_id` del token (consulta a `accounts`/`identity`, cache corta) |
| Topic ajeno o inexistente | Respuesta idéntica `4403 topic_forbidden` para ambos casos (anti-enumeración; nunca se confirma existencia) |
| Cross-cuenta | Solo con scope `admin` **y** `account_id` explícito en la suscripción; toda suscripción cross-cuenta se audita (`audit` + `correlation_id`) |
| Scope mínimo por topic | `ticks/candles/system` → `read` (o anónimo-simulado para datos públicos si se habilita); `account/orders/positions/transactions` → `read` + pertenencia; `notifications` → sesión propia |
| Cambio de autorización | Revocación de sesión o pérdida de permiso en caliente → `subscriptions.revoked` + cierre de esos topics (y cierre total si la sesión caduca) |
| Límite de topics | Máx. **50 suscripciones activas** por conexión (ver §6) |

---

## 3. Envelope de Mensajes y Ciclo de Vida

### 3.1 Envelope canónico (todos los frames de datos)

```json
{
  "type": "tick",
  "topic": "ticks:SYMBOL_100",
  "seq": 1048291,
  "ts": "2026-09-27T14:32:10.123Z",
  "mode": "DEMO",
  "data": { "bid": "104.21", "ask": "104.23", "ts": "2026-09-27T14:32:10.120Z" }
}
```

| Campo | Regla |
|---|---|
| `type` | `tick` / `candle` / `event` / `ack` / `error` / `advisory` / `auth.ok` / `auth.expired` |
| `topic` | Sometido al §4; el servidor solo envía topics suscritos y autorizados |
| `seq` | Entero monotónico **por topic** (no global); base 1 por conexión-tema; ver §5 |
| `ts` | UTC del servidor (no del cliente) |
| Payload de `type: "event"` | Reutiliza el **envelope de `P-event-catalog.md`** (`event_id`, `event_type`, `schema_version`, `aggregate_id`, `correlation_id`, `producer`, `payload`) — un único contrato de evento para bus y WS |

### 3.2 Mensajes de control (cliente → servidor)

| Mensaje | Efecto | Respuesta |
|---|---|---|
| `{"type":"auth", …}` | Autentica la conexión (§2) | `auth.ok` o cierre `4401` |
| `{"type":"subscribe","id":"…","topics":["a","b"]}` | Suscribe (validación por topic, §2.3) | `ack` con `id` y `results[]` por topic: `ok` / `forbidden` / `rate_limited` / `invalid_topic` |
| `{"type":"unsubscribe","id":"…","topics":[…]}` | Cancela suscripción | `ack` (idempotente: desuscribir lo no suscrito = `ok`) |
| `{"type":"ping"}` / pong del servidor | Heartbeat a nivel de aplicación | `{"type":"pong","ts":…}` |
| `{"type":"resync","topic":"…","from_seq":N}` | Pide reanudación tras hueco | `ack` + `snapshot` (evento con `seq` actual) + reanudar deltas; si `from_seq` ya no está en buffer → `resync.required` (§5) |

Los mensajes de cliente se validan con **JSON Schema** estricto (campos desconocidos rechazados, `type` de enum, profundidad ≤ 4, frame ≤ 64 KiB).

### 3.3 Heartbeat y timeouts

| Parámetro | Valor objetivo | Acción al incumplirse |
|---|---|---|
| `ping` del servidor cada | 20 s | — |
| `pong` esperado en | ≤ 20 s | 1er fallo → `advisory: heartbeat_degraded` |
| | | 2 fallos consecutivos (40 s sin pong) → cierre `4408` (heartbeat timeout) |
| Autenticación | Primer frame `auth` en ≤ 5 s | Cierre `4401` |
| Inactividad sin suscripciones | > 120 s | Cierre `4404` (idle) — ahorra recursos; reconectable |
| Ping del cliente | Permitido cada ≥ 5 s | Más frecuente → `4429` de control |

### 3.4 Reconexión del cliente (especificada para SDK)

| Parámetro | Regla |
|---|---|
| Política | Backoff exponencial con **jitter**: base 500 ms, factor 2, máx 30 s, jitter ±20 % (full jitter preferente) |
| Orden de recuperación | Nuevo ticket → `auth` → `subscribe` con los topics previos → `resync` por topic con `from_seq` → backfill REST si el servidor lo pide |
| Retención de eventos | El servidor retiene un **ring buffer por topic** (últimos 1000 mensajes o 5 min, lo que sea menor); fuera de ese rango → `resync.required` |
| Backfill REST | `GET /api/v1/orders`, `/api/v1/positions`, `/api/v1/wallet/transactions`, `/api/v1/deposits`… con cursor; los ticks/v históricos vía `/api/v1/market-data/candles/{symbol}/{timeframe}` |
| Idempotencia cliente | Los SDK reenvían `subscribe` con `id` idempotente; un `ack` perdido no duplica suscripción |

---

## 4. Catálogo de Topics

### 4.1 Definición

| Topic | Parámetros | Quién puede suscribirse | Fase del hub | Datos |
|---|---|---|---|---|
| `ticks:{symbol}` | `symbol` del catálogo | Cualquier autenticado (`read`); público simulado opcional | 3 | Bid/ask último tick |
| `candles:{symbol}:{timeframe}` | `timeframe` ∈ `1m 5m 15m 1h 4h 1d` | Autenticado (`read`) | 3 | Vela actual (update) y vela cerrada |
| `account:{id}` | `account_id` UUIDv7 | Dueño de la cuenta o `admin` | 3 | Cambios de estado de cuenta y margen |
| `orders:{account}` | `account_id` | Dueño o `admin` | 4 | Ciclo de vida de órdenes |
| `positions:{account}` | `account_id` | Dueño o `admin` | 4 | Aperturas, cierres, PnL |
| `transactions:{account}` | `account_id` | Dueño o `admin` | 4 | Movimientos de dinero (depósitos/retiros/ledger) |
| `notifications:{user}` | implícito = sujeto del token | Solo el propio usuario | 3 | Avisos in-app (seguridad, KYC, pagos) |
| `system:announcements` | — | Cualquier autenticado | 3 | Mantenimiento, incidentes, avisos de plataforma |

> Los topics `ticks` y `candles` transportan **streaming de datos de mercado**, no eventos de negocio del catálogo: en la tabla §4.2 figuran como "— (sin evento en `P`)".

### 4.2 Topic → Eventos (`P-event-catalog.md`) → Fase → Criticidad

| Topic | Eventos P (nº) | Fase | Criticidad | Notas de entrega |
|---|---|---|---|---|
| `ticks:{symbol}` | — (stream de datos; sin evento en `P`) | 3 | `MEDIUM` | Dato público; pérdida = saltos de precio en gráfico → resync por snapshot |
| `candles:{symbol}:{timeframe}` | — (stream de datos; sin evento en `P`) | 3 | `MEDIUM` | Vela en vivo + cierre; sin huecos silenciosos (marcar `gap: true` si no hay dato) |
| `account:{id}` | AccountCreated (12), KycApproved (14), KycRejected (15), DemoAccountCreated (16), DemoBalanceReset (17), MarginCallTriggered (32), StopOutTriggered (33) | 3 (hub) / 2 y 4 (eventos) | `CRITICAL` | Margin call/stop-out exigen entrega prioritaria y reentrega garantizada |
| `orders:{account}` | OrderCreated (25), OrderAccepted (26), OrderRejected (27), OrderFilled (28), OrderCancelled (29), RiskLimitExceeded (34), FeeCharged (36) | 4 | `CRITICAL` | Orden por `aggregate_id` + `seq`; sin reordenamiento |
| `positions:{account}` | PositionOpened (30), PositionClosed (31), PnlRealized (35), SwapApplied (37) | 4 | `CRITICAL` | PnL se recalcula en cliente a partir de `ticks`, no se emite por tick |
| `transactions:{account}` | DepositRequested/Completed/Failed (18–20), WithdrawalRequested/Approved/Completed/Rejected (21–24), LedgerPosted (38) | 4 (ledger) / 6 (payments) | `CRITICAL` | Dinero: entrega at-least-once + dedup por `event_id` en cliente |
| `notifications:{user}` | UserRegistered (1), UserEmailVerified (2), UserLoggedIn (3), LoginFailed (4), MfaEnabled/Disabled (5–6), SessionRevoked (7), PasswordResetRequested/Completed (8–9), ApiKeyCreated/Revoked (10–11), KycRejected (15), DepositFailed (20), WithdrawalRejected (24) | 3 (hub) / 1 y 6 (eventos) | `HIGH` (seguridad) / `MEDIUM` | Avisos de seguridad entregados siempre; opt-out solo para marketing |
| `system:announcements` | — (evento operativo de plataforma; no pertenece a `P`) | 3 | `HIGH` | Mantenimiento/kill-switch se envían con `priority` y sin posibilidad de desuscripción del todo (máx. 3 fijos) |

**Reglas comunes de publicación**: los eventos llegan al hub desde el mismo outbox/Redpanda que el resto de consumidores (at-least-once ⇒ el cliente deduplica por `event_id`); el hub nunca inventa ni reformatea `payload` de eventos `CONFIDENTIAL` — aplica las mismas reglas de `P` §4 (sin PII en claro fuera de los tópicos autorizados).

---

## 5. Sequence Numbers, Resync y Backpressure

### 5.1 Secuencias

| Regla | Detalle |
|---|---|
| Alcance | `seq` es **por topic** (el orden global no está garantizado entre topics) |
| Monotonía | Estrictamente creciente por topic; el cliente detecta hueco (`seq_actual > seq_previo + 1`) |
| Fuente de orden | En `account/orders/positions/transactions` el orden hereda la partición por `aggregate_id` del bus (`P` §3.2): eventos del mismo agregado llegan en orden |
| Tratamiento de hueco | Cliente envía `resync {topic, from_seq}` → servidor responde `snapshot` (estado actual con `seq` nuevo) + reenvía deltas posteriores; si el rango ya no está en el ring buffer → `resync.required` ⇒ **backfill REST** + snapshot nuevo |
| Persistencia | `seq` vive solo en la conexión (ring buffer en memoria del hub); tras reconexión se emite snapshot nuevo con `seq` reiniciado — el cliente nunca asume continuidad entre conexiones sin `snapshot` |
| Garantía | At-least-once dentro de la conexión; sin exactly-once (dedup por `event_id` en el cliente, igual que en el bus) |

### 5.2 Backpressure y slow consumer

| Etapa | Umbral objetivo | Acción |
|---|---|---|
| Cola por conexión | ≤ 1000 frames **o** ≤ 4 MiB pendientes | Operación normal |
| Aviso (`advisory`) | ≥ 70 % de la cola (700 frames o 2,8 MiB) durante 2 ventanas de 1 s | Frame `{"type":"advisory","code":"slow_consumer","queue_pct":70}`; se registra métrica |
| Desconexión | ≥ 100 % de la cola o cola no drenada > 10 s | Cierre del servidor con `4410` (backpressure); **nunca** se descartan frames de otros consumidores para servir a este |
| Política | Los frames de `account/orders/positions/transactions` **nunca** se descartan selectivamente: o se entrega todo o se desconecta el consumidor y este recupera por snapshot/backfill | Aislamiento entre consumidores |
| Prioridad | `system:announcements` y margin/stop-out se encolan primero (evitar head-of-line blocking en avisos) | — |
| Métrica obligatoria | `ws_backpressure_disconnects_total` debe mantenerse ~0; subir = cliente defectuoso o limites mal dimensionados (§7) |

### 5.3 Rate limits de mensajes por conexión

| Clase | Límite | Superación |
|---|---|---|
| Frames entrantes (control) | 20/s y 60/min por conexión | `4429` + cierre tras 3 infracciones |
| `subscribe`/`unsubscribe` | 30/min por conexión | `ack` con `rate_limited` (no cierre) |
| Suscripciones activas | 50 por conexión | `ack` `topic_limit` |
| Conexiones por usuario | 5 simultáneas | Rechazo `4429` en handshake |
| Conexiones por IP | 50 simultáneas | Rechazo `4429` en handshake |
| Frames salientes | Regulados por cola (§5.2); sin límite de tasa por topic salvo cuota de salida global del hub | Backpressure |

---

## 6. Seguridad

| Control | Regla |
|---|---|
| Transporte | Solo `wss://` en cualquier entorno no local; HSTS |
| Tokens de un solo uso | El `ticket` de handshake se invalida al consumirse; reintento = `4401` (previene replay y cross-user) |
| Validación de payloads | JSON Schema estricto por tipo de mensaje; frame ≤ 64 KiB; profundidad ≤ 4; strings ≤ 1 KiB; `symbol` validado contra catálogo; cualquier violación → `4400` y, si es reiterado, cierre |
| Aislamiento de cuentas | Suscripción solo a recursos del token (§2.3); el hub aplica filtro servidor-side por `account_id` además de la autorización de suscripción (defensa en profundidad) |
| Origen | `Origin` contra allowlist (misma `DOMAIN` + orígenes de app declarados); rechazo → cierre `4403` |
| Compresión | `permessage-deflate` **deshabilitado** en tópicos con datos de cuenta (evita canaux laterales de compresión); permitido en `ticks`/`candles` |
| Límites de conexión | §5.3 (por usuario, por IP, total por instancia) |
| Enumeración | Respuesta idéntica para topic inexistente y ajeno (§2.3) |
| Log | Nunca loggear ticket/token; `connection_id` + `user_id` hasheado + `topic` permitido; datos `CONFIDENTIAL` no van a logs de aplicación (`P` §4) |
| Auditoría | Se auditan: handshake exitoso/fallido, suscripciones cross-cuenta, desconexiones por seguridad y revocaciones (`correlation_id`/`request_id`) |
| Multitenancia | Un hub no mezcla modos: las conexiones `DEMO` no reciben tópicos `LIVE` y viceversa (`mode` visible en cada frame) |
| Dependencias | Solo WebSocket/JSON de la stack Fase 1 (FastAPI/Starlette); sin proveedor externo de mensajería en tiempo real (`00-decisions` §4) |

---

## 7. Objetivos de Latencia y Métricas

### 7.1 Objetivos internos (no son afirmación de cumplimiento)

| Métrica | Objetivo interno (p95 salvo indicación) | Condición de validez |
|---|---|---|
| Handshake completo (upgrade + `auth.ok`) | ≤ 300 ms en red local/region | Medible solo con benchmark (k6/WebSocket, `BUILD-032`) |
| Fan-out evento → frame en el cliente ( mismo region) | p50 ≤ 100 ms, p95 ≤ 250 ms | Requiere benchmark con dataset sintético y publicación de umbrales en CI |
| `ack` de `subscribe` | ≤ 200 ms | Idem |
| Entrega de `system:announcements` | p95 ≤ 1 s | Idem |
| Tasa de frames por conexión saliente | sostenido ≥ 500 msg/s sin backpressure | Idem (define el dimensionado de colas §5.2) |
| Detección de desconexión (heartbeat) | ≤ 40 s (2 fallos de pong) | Determinista por configuración, no requiere benchmark |

> **Ninguno de estos valores está verificado**: son objetivos de diseño. Se declaran cumplidos solo después de un benchmark publicado (Fase 3, `BUILD-032`), con los resultados adjuntos a este documento.

### 7.2 Métricas a instrumentar (OpenTelemetry + Prometheus)

| Métrica | Tipo | Labels | Para qué |
|---|---|---|---|
| `ws_connections_active` | gauge | `hub`, `mode`, `topic_tier` | Capacidad y escalado |
| `ws_connections_total` | counter | `result` (`ok`, `auth_failed`, `rate_limited`, `origin_rejected`) | Abuso y salud del handshake |
| `ws_messages_sent_total` / `ws_messages_recv_total` | counter | `topic`, `type` | Throughput por topic |
| `ws_subscriptions_active` | gauge | `topic_pattern` | Uso real de tópicos (retirar los que nadie usa) |
| `ws_disconnects_total` | counter | `reason` (`heartbeat_timeout`, `backpressure`, `auth_expired`, `client`, `server_shutdown`, `origin`, `rate_limit`) | **Diagnóstico primario** |
| `ws_backpressure_advisories_total` | counter | `topic_tier` | Detección temprana de slow consumers |
| `ws_backpressure_disconnects_total` | counter | `topic_tier` | Desconexiones por cola llena (objetivo ≈ 0) |
| `ws_queue_depth_bytes` / `ws_queue_depth_frames` | histogram | `hub` | Dimensionado de colas (§5.2) |
| `ws_heartbeat_timeouts_total` | counter | — | Redes móviles/proxies defectuosos |
| `ws_auth_failures_total` | counter | `cause` (`expired`, `invalid`, `replay_ticket`, `timeout`) | Seguridad del handshake |
| `ws_subscribe_denied_total` | counter | `cause` (`forbidden`, `scope`, `account_mismatch`) | Intentos de BOLA |
| `ws_resync_requests_total` | counter | `cause` (`gap`, `reconnect`, `buffer_expired`) | Calidad de entrega y tamaño de ring buffer |
| `ws_delivery_latency_seconds` | histogram | `topic_tier` | Contra objetivos §7.1 (requiere reloj sincronizado) |
| `ws_reconnects_total` | counter | `client` (opcional, anonimizado) | Estabilidad del SDK |

### 7.3 Alertas mínimas (Fase 3)

| Condición | Severidad |
|---|---|
| `ws_backpressure_disconnects_total` tasa > 0 durante 5 min | warning |
| `ws_disconnects_total{reason="server_shutdown"}` > 0 fuera de mantenimiento | warning |
| p95 de `ws_delivery_latency_seconds` > 2× objetivo interno | warning (severidad alta tras benchmark de línea base) |
| `ws_connections_active` > 80 % de capacidad de la instancia | warning |
| `ws_auth_failures_total` crecimiento abrupto | warning de seguridad |
| `ws_subscribe_denied_total{cause="account_mismatch"}` > 0 sostenido | **alta** (intento de acceso a cuentas ajenas → auditar) |

---

## 8. Pendientes / No Determinado

| Tema | Estado |
|---|---|
| Hub distribuido (fan-out multi-instancia vía bus) vs hub único | `DECIDIR` Fase 3 (afecta a `seq` global y ring buffer) |
| Compresión selectiva y multiplexado por instancia | `DECIDIR` Fase 3 con benchmark |
| Auth por passkey/WebAuthn en el handshake | `PENDIENTE` (igual que identity, `D-domain-map` §5) |
| Guías de rate limit por plano de usuario (freemium/pro) | `DECIDIR` Fase 5 (sandbox API/WS, `BUILD-052`) |
| Entrega garantizada entre conexiones (resume persistente) | `NO ADOPTADO` en v1: se cubre con snapshot + backfill REST |

---

*Fin del documento R-websocket-map.md*
