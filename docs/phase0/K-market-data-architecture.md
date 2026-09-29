# K — Arquitectura de Market Data (Market Data Layer)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

> **Regla de lectura**: diseño objetivo, no afirmación de implementación ni de acceso a feeds reales. El estado por componente se declara en `W-build-now.md` y `X-blocked-to-live.md`. Complementos: `Q-api-map.md` §2.7/§3 (REST e interna), `R-websocket-map.md` §4 (topics WS), `P-event-catalog.md` (eventos de negocio), `00-decisions.md` (decisiones canónicas), `H-trading-architecture.md` (consumidor `trading`/`risk`).
> **Afirmación explícita (actualizada 2026-09-28)**: en este repositorio **no existe ningún feed de mercado contratado** ni credenciales de proveedor, ni datos con derechos de redistribución para trading. X-07 sigue bloqueada para ticks/streams usados por `trading`/`risk` (todo dato de mercado de Fases 3–5 sigue siendo sintético y etiquetado como simulado).
> **Excepción informativa verificada (2026-09-28)**: `services/market-data` consume APIs **públicas keyless** de referencia — BCE vía Frankfurter (primario) y Data Portal del ECB (failover) para forex; Kraken (primario) y CoinGecko (failover) para crypto — únicamente para el snapshot **informativo** `GET /api/v1/market-data/overview` de la portada (`simulated: false`, con `source`/`ts`/`stale` y atribución obligatoria). Sin contrato ni redistribución: ver `docs/API_INTEGRATIONS.md`. Regla de no-ficción: jamás se fabrica un precio (último dato bueno con `stale=true`, o `unavailable`).

## 0. Estado de implementación del servicio (2026-09-28)

| Elemento | Estado | Detalle |
|---|---|---|
| Servicio `services/market-data` (FastAPI, puerto 8084, imagen propia, K8s/compose) | IMPLEMENTADO | `GET /healthz`, `GET /readyz`, `GET /api/v1/market-data/overview`; sin BD/colas/secretos |
| Contratos DTO (`platform_contracts/market_data.py`: `MarketOverview`, `MarketClassOverview`, `OverviewQuote`) | IMPLEMENTADO | Spec canónico `platform-contracts/openapi/market-data.yaml` + gate de deriva en CI |
| Protocols de adapters (§1.1 target) | PARCIAL | Hoy existe `MarketDataProvider.fetch_quotes()` (batch por clase de activo) en `market_data/domain/protocols.py`; `get_quote`/`get_tickers`/`get_market_status`, `HistoricalDataProvider` y `StreamingProvider` quedan para Fases 2–3 |
| Cache TTL + circuit breaker + failover primario→secundario | IMPLEMENTADO | FX TTL 900 s (referencia diaria BCE), crypto TTL 60 s (límite Kraken 1 req/s); breaker 3 fallos → abierto 30 s → sonda; implementación propia sin dependencias nuevas |
| Regla no-ficción (K §6.1) | IMPLEMENTADO | Sin fuente → `unavailable` (portada: "dato no disponible"); fuente caída → último snapshot con `stale=true` y `ts` original |
| Gateway (`PUBLIC_PATHS`, `market_data_url`, `/healthz` agregado) | IMPLEMENTADO | Ruta pública sin JWT; tasa global del gateway aplica |
| Streaming WS, ticks/velas, symbol master, histórico | PENDIENTE | Fases 2–3 (ver `R-websocket-map.md`, `Q-api-map.md` §2.7) |

---

## 1. Capa desacoplada de market data (interfaces y reglas de adapter)

### 1.1 Contratos canónicos (Protocols Python, Pydantic v2)

Los contratos viven en el dominio de `services/market-data` (`market_data/domain/`) con sus DTOs versionados en `packages/platform-contracts/`; ningún módulo importa un cliente de proveedor, solo estos tipos.

```python
class MarketDataProvider(Protocol):
    async def get_quote(self, symbol: str) -> Quote: ...
    async def get_tickers(self, symbols: Sequence[str] | None = None) -> list[Ticker]: ...
    async def get_market_status(self, symbol: str | None = None) -> MarketStatus: ...
    def capabilities(self) -> ProviderCapabilities: ...  # asset classes, granularidad, REST/WS, rate limits


class HistoricalDataProvider(Protocol):
    async def get_candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime, cursor: str | None, limit: int
    ) -> Page[Candle]: ...
    async def get_ticks(
        self, symbol: str, start: datetime, end: datetime, cursor: str | None, limit: int
    ) -> Page[Tick]: ...
    async def get_symbol_metadata(self, symbol: str) -> SymbolMetadata: ...


class StreamingProvider(Protocol):
    async def subscribe_ticks(self, symbols: Sequence[str]) -> AsyncIterator[Tick]: ...
    async def subscribe_candles(self, subscriptions: Sequence[tuple[str, str]]) -> AsyncIterator[Candle]: ...
    async def unsubscribe(self, subscriptions: Sequence[tuple[str, str]]) -> None: ...
    async def health(self) -> StreamHealth: ...  # heartbeat, lag, última recepción


class SyntheticDataProvider(Protocol):
    """Emisor del motor interno. Misma forma canónica que un proveedor externo."""

    async def get_quote(self, symbol: str) -> Quote: ...
    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[Tick]: ...
    def parameters_ref(
        self, symbol: str
    ) -> SyntheticParamsRef: ...  # seed + versión de parámetros + versión de algoritmo
```

### 1.2 Reglas de desacople (obligatorias)

| Regla | Detalle |
|---|---|
| **Adapters, nunca núcleo** | Cada proveedor externo es un adapter en `market_data/infrastructure/providers/<nombre>/`. El dominio solo conoce los Protocol de §1.1. Ninguna clase de dominio importa SDK, cliente HTTP/WS ni tipos de un tercero |
| **Normalización a canónico** | Todo dato entrante se convierte a `Quote`/`Tick`/`Candle`/`SymbolMetadata` (§2) antes de tocar bus, base o API. Los tipos del proveedor no cruzan el boundary del adapter |
| **Timeout por operación** | Presupuesto explícito (`connect_timeout_ms`, `read_timeout_ms`) por adapter y método; timeout → error tipado `PROVIDER_TIMEOUT`, nunca bloque indefinido |
| **Retries** | Solo operaciones idempotentes de lectura; backoff exponencial con jitter, intentos máximos y `Retry-After` respetado; los streams se reconectan, no se "reintentan" mensajes |
| **Circuit breaker** | Por adapter y por símbolo (§6); abierto → failover al siguiente adapter o a degradación, jamás a un precio inventado |
| **Failover** | Orden de preferencia configurable y versionada; mínimo **2 proveedores** por clase de datos crítica antes de LIVE (`V-risk-register` R-008, `U-external-dependencies` #1); objetivo de conmutación <500 ms (verificable solo con proveedor real) |
| **Idempotencia y orden** | Cada tick normalizado lleva `source`, `provider_seq` (si existe) y `recv_ts`; la deduplicación es por `(symbol, source, provider_seq|ts, price)` (§4.4) |
| **Sin acoplamiento a rutas/WS** | El hub WS (`R-websocket-map`) y las rutas REST (`Q-api-map` §2.7) consumen el servicio normalizado; desconocen por completo qué adapter está activo |
| **Observabilidad** | Métricas por adapter: latencia, errores, lag, breaker state, ticks descartados; trazas OTel con `provider` como atributo |

### 1.3 Implementaciones previstas

| Implementación | Propósito | Estado |
|---|---|---|
| `MockMarketDataProvider` / `MockHistoricalDataProvider` | Determinista (seed), etiquetado `simulated: true` y `source: MOCK` | `MOCK` (estructura Fase 1, servicio Fase 3) |
| `SyntheticMarketEngineAdapter` | Expone el motor interno (§5) bajo `SyntheticDataProvider` | `PENDIENTE` (Fase 5, `BUILD-046`) |
| `<ProveedorA>Adapter`, `<ProveedorB>Adapter` | Feeds externos reales | `REQUIERE PROVEEDOR` — **no se nombran ni simulan proveedores concretos** |

---

## 2. Modelo de datos canónico

Precios siempre como cadena decimal / `Decimal` (nunca `float`, `00-decisions` §5); todos los tiempos en **UTC RFC 3339** con precisión ≥ ms.

| Entidad | Campos obligatorios | Notas |
|---|---|---|
| **Quote** | `symbol`, `bid`, `ask`, `last`, `ts` (UTC) | `bid ≤ ask` obligatorio; `spread` derivado; `source`, `simulated`, `stale` (§6) opcionales pero recomendados; sin liquidez agregada inventada |
| **Ticker** | `quote` + `volume_24h?`, `change_pct?`, `high_24h?`, `low_24h?` | Los campos 24h solo si el originario los provee; si no, `null`, nunca estimados en silencio |
| **Tick** | `symbol`, `price`, `side?` (`buy`/`sell`/`na`), `size?`, `ts` (UTC), `source`, `provider_seq?` | Granularidad de mercado; `recv_ts` de recepción interna se guarda aparte para medir latencia |
| **Candle (OHLC)** | `symbol`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `ts` (UTC de apertura) | Invariantes: `low ≤ min(o,c) ≤ max(o,c) ≤ high`; `volume ≥ 0`; timeframes soportados: `1m 5m 15m 1h 4h 1d` (`R` §4.1) |
| **SymbolMetadata** | `symbol`, `display_name`, `asset_class`, `base_currency`, `quote_currency`, `tick_size`, `contract_size`, `pip_size`, `min_volume`, `max_volume`, `volume_step`, `margin_requirements`, `trading_hours`, `jurisdiction_restrictions`, `fee_schedule`, `swap_configuration`, `status` | Symbol master versionado (`valid_from`, `valid_to`, `version`); reglas de redondeo derivadas de `tick_size`; toda orden fuera de spec se rechaza tipado (`BUILD-028`) |
| **TradingSession** | `symbol`/`asset_class`, `weekday`, `open_utc`, `close_utc`, `timezone` (IANA), `holiday_calendar`, `session_type` (`regular`/`pre`/`post`) | Las sesiones se declaran por zona horaria y se convierten a UTC; feriados por calendario versionado, no hardcodeados en lógica |
| **MarketStatus** | `symbol`, `status` (`open`/`closed`/`halted`), `reason`, `next_open`, `next_close`, `as_of` | `halted` = suspensión explícita (noticia, breach, mantenimiento); distinto de `closed` (horario) y de `stale` (calidad de feed) |

Almacenamiento (`O-database-strategy`): schema `market_data` en PostgreSQL 17 + TimescaleDB — `symbols`, `instrument_specs`, `ticks` (hypertable), `candles` (hypertable + continuous aggregates `candles_1m`, `candles_1h`), `provider_status`; retención objetivo 2 años (ticks) y 7 años (velas), `DECIDIR` de coste en Fase 3.

---

## 3. Catálogo de mercados preparado arquitectónicamente

El symbol master soporta las clases siguientes; la **habilitación comercial** de cada una está sujeta a jurisdicción, licencia y bandera de producto (`S-mvp-scope`, `X-blocked-to-live`).

| Asset class | Horario / sesiones | Feriados | Fuente de precio (hoy) | Estado de oferta |
|---|---|---|---|---|
| **Forex** | 24/5 (cierre diario ~21:00 UTC ± horario de verano; apertura domingo 22:00 UTC) con sesiones Asia/Europa/América y solapes | Cierre sáb; festivos bancarios por calendario (`holiday_calendar` por divisa); paridades exóticas con calendarios propios | `REQUIERE PROVEEDOR` (feed externo); hasta entonces mock/sintético etiquetado | `REQUIERE CONTRATO` (redistribución) + gating por jurisdicción |
| **Crypto** | 24/7, sin cierre | Ningún festivo de mercado; riesgo de mantenimiento del venue documentado como `halted` | `REQUIERE PROVEEDOR`; hasta entonces mock/sintético | `REQUIERE CONTRATO` para datos de terceros; oferta sujeta a `REQUIERE LICENCIA/REGULACIÓN` por jurisdicción |
| **Equities** | Sesión regular del mercado local (p. ej. ~14:30–21:00 UTC para bolsas europeas/americanas) + pre/post si el venue lo permite | Festivos nacionales del calendario de la bolsa; **corporate actions** (splits, dividendos) requieren ajuste y evento propio | `REQUIERE PROVEEDOR`; sin acceso real | `REQUIERE LICENCIA/REGULACIÓN` + `REQUIERE CONTRATO` |
| **Stock Indices** | Horario del mercado subyacente; cierre por rueda local | Festivos de la bolsa base; una sola sesión aunque el índice agregue valores | `REQUIERE PROVEEDOR`; hasta entonces mock/sintético | `REQUIERE CONTRATO`; CFD/derivados sobre índice → `REQUIERE LICENCIA/REGULACIÓN` |
| **Commodities** | Rueda del contrato físico/futuro de referencia; ventanas de liquidez por sesión | Festivos del mercado de referencia; ruedas nocturnas según producto | `REQUIERE PROVEEDOR` | `REQUIERE LICENCIA/REGULACIÓN` + `REQUIERE CONTRATO` |
| **Metals** (subclase de commodities, específica por liquidez) | Similar a commodities; spot 24/5 con cierre diario | Festivos bancarios y de mercados OTC | `REQUIERE PROVEEDOR` | `REQUIERE CONTRATO` |
| **ETFs** | Sesión de la bolsa cotizada | Festivos de la bolsa; acciones de ETF como equity | `REQUIERE PROVEEDOR` | `REQUIERE LICENCIA/REGULACIÓN` + `REQUIERE CONTRATO` |
| **Derived / Synthetic** (índices propios) | **24/7 configurable** (`simulation regime`); sin festivos salvo maintenance window | No aplica: calendario propio de mantenimiento visible al usuario | Generador interno (`SyntheticDataProvider`, §5) | Solo simulación etiquetada; ofrecerlo con dinero real → `REQUIERE LICENCIA/REGULACIÓN` |
| **Opciones / contratos estructurados** | Según subyacente y mercado | Los del subyacente + fechas de vencimiento/expiration calendar | `REQUIERE PROVEEDOR` | **`REQUIERE LICENCIA/REGULACIÓN`** — solo se habilita cuando sea legalmente admisible en la jurisdicción de la cuenta; sin dictamen, el catálogo los omite (no se muestran ocultos ni se simulan como negociables) |
| **CFDs / riesgo-limitado** | Hereda sesión del subyacente; en sintéticos, 24/7 | Hereda | Feed externo o motor interno | Fase 5 solo DEMO; LIVE → `REQUIERE LICENCIA/REGULACIÓN` (`BUILD-043`, `BUILD-045`) |

Reglas transversales del catálogo:

1. **Un símbolo = un asset_class + un calendario + una fuente de precio** declarados en `SymbolMetadata`; la fuente (`MOCK`, `SYNTHETIC`, `PROVIDER:<id>`) viaja en cada tick y en la respuesta REST.
2. `jurisdiction_restrictions` y `fee_schedule`/`swap_configuration` se evalúan por jurisdicción de la cuenta; sin regla cargada → producto **no disponible** (fail-closed, no fail-open).
3. Ninguna clase se activa por asunción: habilitar = fila versionada + bandera + (si aplica) licencia verificada en `X-blocked-to-live.md`.

---

## 4. Ingesta y distribución

### 4.1 Pipeline

```text
[Adapter proveedor / SyntheticDataProvider]
        │  (normalización canónica: tipos, decimales, UTC, source)
        ▼
[Normalizador + validador]  ── descarte/cuarentena ──► métricas + alerta (§6)
        │
        ▼
[Redpanda]  market.ticks.{symbol} · market.candles.{symbol}.{tf} · market.status.{symbol}
        │                    │                          │
        ▼                    ▼                          ▼
[persistencia market_data]  [agregador tick→vela]   [hub WS /ws/v1]
 (ticks/candles, huecos      (1m…1d, BUILD-030)      ticks:{symbol} ·
  marcados explícitos)                               candles:{symbol}:{tf}
        │                                                ▲
        └──► REST /api/v1/market-data/* (snapshot, histórico, status, symbols)
             e interna /internal/v1/market-data/quote/{symbol}  ◄── trading / risk
```

### 4.2 Topics del bus (Redpanda) y correspondencia con `R-websocket-map`

| Topic del bus | Key de partición | Retención objetivo | Topic WS de salida |
|---|---|---|---|
| `market.ticks.{symbol}` | `symbol` | 7 días (`delete`) — es stream, no archivo | `ticks:{symbol}` |
| `market.candles.{symbol}.{tf}` | `symbol` | 30 días (`delete`) | `candles:{symbol}:{tf}` |
| `market.status.{symbol}` | `symbol` | 90 días (`delete`) | `ticks` (advisory) + `system:announcements` si `halted` |
| `market.symbols.changed` | `symbol` | 30 días | invalidación de cache del cliente |
| `market.dlq` | `adapter` | 30 días (`delete`) | — (interno) |

- Los tópicos WS son los de `R-websocket-map` §4.1; el hub traduce bus → frame con `seq` monotónico por topic, `ts` UTC de servidor y `mode`.
- `ticks`/`candles` **no** son eventos de `P-event-catalog.md` (allí figuran como "— (sin evento en `P`)"); el dominio `market-data` sí publica sus eventos operativos propios (`MarketDataConnected`, `TickReceived`, `CandleClosed`, `SymbolUpdated` — `D-domain-map` §1) en su topic de dominio, con el envelope estándar (`P` §1) cuando se registren.
- Outbox obligatorio para esos eventos operativos; los ticks usan productor directo con acks `all` (son reconstruibles por backfill, no requieren outbox transaccional).

### 4.3 REST para histórico y configuración (`Q-api-map` §2.7)

`GET /api/v1/market-data/symbols` · `/ticks/{symbol}` · `/ticks` (rango ≤ 24 h) · `/candles/{symbol}/{timeframe}` (cursor + `from`/`to`) · `/status` · `GET /api/v1/admin/market-data/providers` (F7) · interna `GET /internal/v1/market-data/quote/{symbol}`. Paginación por cursor opaco (`Q` §1.4), sin offset. Rate limit: 300/min por token (`Q` §5).

### 4.4 Secuenciación, huecos, duplicados y reloj

| Tema | Diseño |
|---|---|
| **Secuenciación** | `provider_seq` (si el originario lo da) normalizado; en el hub, `seq` monotónico **por topic** (`R` §5). Orden garantizado por partición `symbol` en el bus |
| **Detección de faltantes** | (a) en el bus: hueco de `provider_seq` ⇒ evento `GapDetected` + job de backfill; (b) en WS: `seq_actual > seq_previo + 1` ⇒ `resync` del cliente (`R` §5.1); (c) en velas: bucket temporal sin ticks ⇒ candle marcado `gap: true`, **nunca** fabricado con el último precio |
| **Duplicados** | Ventana deslizante por `(symbol, source, provider_seq)`; sin `provider_seq`, ventana temporal ±ε sobre `(ts, price, size)`; consumidores del bus idempotentes por `event_id`/clave de mensaje (`P` §3.3) |
| **Backfill** | Job por rango hueco: prioriza `HistoricalDataProvider`, respeta rate limit, marca `backfilled: true`, verifica invariantes OHLC y contigüidad antes de publicar; si no hay proveedor histórico → hueco permanece **explícito** con `gap: true` |
| **Reconciliación** | Cada N minutos se comparan último tick persistido, último del bus y último del hub; divergencia > umbral ⇒ alerta + resync. Diaria: vela agregada desde ticks vs. vela del proveedor (si la hay) ⇒ alerta en desajuste |
| **Reloj** | UTC como referencia canónica (`platform_kernel.time`); NTP en todos los nodos; `ts` de evento = reloj del productor, `recv_ts` = reloj receptor; skew máximo tolerado **500 ms** (warning) / **2 s** (crítico, marca el dato como no confiable); skew del cliente no se usa nunca; timestamps fuera de banda o en futuro ⇒ descarte + métrica |
| **Modo** | Cada mensaje lleva `mode`/`simulated`; con `live_trading=false` no se publica nada `LIVE` (`00-decisions` §6, `R` §1) |

---

## 5. Motor de índices sintéticos (Synthetic Market Engine)

Módulo **completamente independiente**: sin imports del resto de `market-data` salvo los contratos canónicos, sin dependencias de red, desplegable y testeable por separado (`market_data/synthetic/`).

### 5.1 Integridad algorítmica (declaración obligatoria)

- Los algoritmos son **originales**, propios, documentados en este repositorio y auditables; se implementan a partir de literatura pública y matemática conocida.
- **Prohibido expresamente** copiar, reimplementar a partir de ingeniería inversa o importar algoritmos, parámetros, curvas, tablas o código propietario de la plataforma de referencia ni de ningún otro operador. Cualquier parecido debe ser estadístico, no deriva de copia; esta cláusula es condición de revisión de PR del módulo.
- Todo algoritmo tiene: descripción matemática en docs, parámetros tipados, tests de oro (fixtures) y número de versión.

### 5.2 Configuración

| Parámetro | Descripción |
|---|---|
| `volatility_profile` | Nivel/base de volatilidad objetivo (anualizada o por tick) y régimen asociado |
| `tick_frequency` | Tasa media de ticks (poisson/constante) con jitter documentado; 24/7 configurable |
| `seed_management` | Semilla raíz por instrumento + entorno; derivación determinista por sesión (KDF/counter), rotación controlada, nunca semilla en logs ni en APIs públicas |
| `price_boundaries` | Suelo/techo duros y banda de precios válidos; al tocar frontera ⇒ rebote o freno según `jump behavior` |
| `jump_behavior` | Saltos discretos (frecuencia, magnitud, distribución) y política al impactar fronteras |
| `mean_reversion` | Opcional: intensidad de reversión a nivel de referencia (`OU`/discreto); puede desactivarse |
| `trend_characteristics` | Drift por fases, persistencia y cambio de régimen declarados |
| `distribution_model` | Familia de innovaciones (p. ej. normal/t-student/pareto-tail) con parámetros explícitos |
| `simulation_regime` | `continuous_24x7` · `session_bounded` · `maintenance_paused`; define calendario propio visible al usuario |

La configuración es un documento versionado (`schema_version` + `params_version`) en el repo, cargado por settings; **cambios de parámetros son PRs auditables**, no mutaciones en caliente sin registro.

### 5.3 Reproducibilidad

- **Invariant**: misma `seed` + misma `params_version` + misma `algorithm_version` ⇒ **misma serie**, bit a bit, en cualquier host (enteros/`Decimal`, sin `float`, sin orden de iteración no determinista, sin tiempo real dentro del generador: el tiempo de simulación es lógico).
- Versionado doble e independiente: `params_version` (semántico) y `algorithm_version`; cualquier bump invalida la equivalencia y queda registrado en changelog del módulo.
- **Registro de auditoría**: por tick/sesión se persiste `seed_ref` (referencia, no la semilla en claro), `params_version`, `algorithm_version`, `session_id` y `symbol` — permite regenerar y verificar series por un auditor sin exponer la semilla.
- Job de verificación nightly: regenera una ventana pasada y compara hash de la serie publicada (mismatch ⇒ alerta crítica y bloqueo de publicación).

### 5.4 Separación obligatoria: desarrollo vs. producción certificada

| Eje | `SIMULATION_DEV` | `SIMULATION_PRODUCTION` |
|---|---|---|
| Flags | `synthetic_dev_mode=true` | requiere `synthetic_production=true` + gate de publicación §5.6 en verde |
| Configuración | perfil de desarrollo (volatilidades altas, seeds fijos de test) | perfil certificado, congelado por versión |
| Datos | nunca persiste como histórico "oficial"; etiqueta `dev` | serie canónica persistida y auditable |
| Etiqueta cliente | `simulated: true`, `generator: SYNTHETIC`, `env: DEV` | `simulated: true`, `generator: SYNTHETIC`, `env: PROD` |
| Quién puede activarlo | cualquier entorno local/CI | solo con PR + revisión + evidencia del gate en CI |

No existe código que publique precios sintéticos sin etiqueta; la etiqueta es obligatoria en REST, WS y base (`REQ-024`: test que falla si falta `simulated:true`).

### 5.5 Identificación inequívoca al usuario

- Todo símbolo sintético lleva `asset_class: DERIVED_SYNTHETIC`, `source: SYNTHETIC` y un `display_name` que identifica al instrumento como **generado por el sistema**; la UI muestra badge permanente en gráfico, ticket y histórico.
- Jamás se mezclan en la misma respuesta con datos de mercado externo sin marca por elemento; un cliente no puede distinguirlos "por error": la distinción es campo de contrato, no estilo visual.
- Ninguna fuente externa puede nutrir un símbolo sintético ni viceversa (aislamiento de topics: `market.ticks.SYN_*` no comparte pipeline con adapters externos).

### 5.6 Tests estadísticos y gate de publicación

| Prueba | Propósito | Umbral default (configurable) |
|---|---|---|
| Distribución de retornos | Bondad de ajuste (χ²/KS) a la `distribution_model` declarada | p ≥ 0.01 |
| Volatilidad | Realizada vs. objetivo por `volatility_profile` (ventanas deslizantes) | desv. ≤ 20 % |
| Autocorrelación | Ljung–Box en retornos (lag 1–20) | p ≥ 0.01 (sin estructura) |
| Runs test | Aleatoriedad de signos | p ≥ 0.01 |
| Estabilidad | Media/varianza en ventanas (estacionariedad) | desv. ≤ umbral |
| Límites de precio | Ninguna violación de `price_boundaries`; toques de frontera contabilizados | 0 violaciones |
| Quiebros | Saltos > `jump` máx. por tick y discontinuidades no explicadas | 0 no explicados |
| Reproducibilidad | Regeneración por seed = serie publicada (hash) | igualdad exacta |

- Umbrales en archivo de configuración versionado; los tests corren en CI con dataset propio.
- **Gate de publicación**: una `params_version`/`algorithm_version` nueva no puede emitir en `SIMULATION_PRODUCTION` hasta que todas las pruebas pasen y se publique el reporte como artefacto del pipeline. Fallo ⇒ bloqueo automático + alerta.
- Riesgo de "overfitting de umbrales": los umbrales se revisan con el Head of Data y quedan en changelog.

### 5.7 Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **Manipulación** (sesgo de precio, capa fina, ventaja de latencia) | Motor determinista con seed/parámetros auditados; límites de tamaño/velocidad/posición por cuenta; throttling + kill switch; monitoreo de desviación (`V-risk-register` R-012) |
| **Deriva** (sesgo sistemático no intencionado) | Test de estabilidad y media; revisión de `drift/trend` por versión; alerta si el retorno acumulado sale de la banda declarada |
| **Seed leakage** (predicción de la serie) | Semilla nunca en logs, APIs, respuestas ni cliente; derivación por sesión con secreto raíz fuera del código; rotación; `seed_ref` opaco en auditoría |
| **Dependencia de un solo generador** | Contrato `SyntheticDataProvider` con dos implementaciones posibles (motor A/B) y conmutación por bandera; fixtures de referencia de otra implementación independiente para comparar propiedades estadísticas (no la serie exacta) |
| **Confusión con precios reales** | Etiqueta obligatoria en contrato + test `REQ-024` + aislamiento de topics + revisión de PR |
| **Abuso del motor en DEV hacia producción** | Flags separados (§5.4), gate de publicación, entorno no activable sin evidencia de CI |

---

## 6. Calidad del feed

| Mecanismo | Regla | Acción |
|---|---|---|
| **Outliers** | Banda por `tick_size`/volatilidad reciente y salto máximo por tick | Punto en cuarentena (no publica) + métrica; revisión humana si se repite; jamás se "corrije" un precio sustituyéndolo por otro inventado |
| **Stale quotes** | `age = recv_ts - ts` > umbral por asset_class (p. ej. 2 s sintéticos/crypto, 30 s equities; configurable) | `stale: true` en la quote; el cliente muestra el último precio **marcado como obsoleto**; para `trading`/`risk` el precio stale no sirve para margen ni SL/TP ⇒ rechazo tipado o congelación |
| **Circuit breaker por proveedor** | Errores/timeout/lag por encima de umbral en ventana ⇒ breaker `open` | Failover al siguiente adapter; si no hay, degradación (§6.1); transiciones a `half_open`/`closed` auditadas |
| **Congelación de mercado** | Si no hay dato fiable de ninguna fuente | `market_status = halted` (o `feed: unavailable`) con `reason` visible; **preferible a publicar un precio falso** |
| **Calidad por símbolo** | `% gaps`, `% stale`, latencia p99, duplicados, violaciones OHLC | Publicado en `GET /api/v1/market-data/status` y en `/admin/market-data/providers` (F7) |
| **Symmetry check** | `bid ≤ ask` y spread dentro de banda | Violación ⇒ descarte del quote + alerta |

### 6.1 Degradación graceful (orden de preferencia)

1. Adapter primario sano → dato normal.
2. Primario degradado → failover a secundario, con `source` cambiado en cada tick.
3. Sin adapters externos → `SyntheticDataProvider`/mock **solo si el símbolo lo permite** y con etiqueta `simulated: true` (nunca para símbolos declarados como externos: eso sería precio falso).
4. Sin ninguna fuente → último precio conocido servido con `stale: true` + `as_of`, o `halted` con `reason`; los consumidores financieros (`trading`, `risk`) reciben `PRICE_UNAVAILABLE` y congelan la operación afectada en lugar de calcular sobre dato viejo.

Métricas mínimas: `md_feed_age_seconds` (p99 ≤ 1 s objetivo, `M-tech-stack` §7), `md_provider_breaker_state`, `md_gaps_total`, `md_stale_ratio`, `md_outliers_quarantined_total`, `md_failovers_total`.

---

## 7. Clasificación de datos y gobernanza de market data

| Dato | Clasificación | Owner/Steward | Retención | Gobernanza |
|---|---|---|---|---|
| Tick/candle de proveedor externo | `PUBLIC` del originario, **`CONFIDENTIAL` contractual para nosotros** (sujeto a licencia) | Data/Market · Head of Data (`D-domain-map` §1) | ticks 2 años / velas 7 años (`DECIDIR` coste) | **Redistribución a clientes ⇒ `REQUIERE CONTRATO`** con el proveedor (derechos de retransmisión verificados legalmente); no se afirma licencia alguna sin evidencia en `X-blocked-to-live.md` X-07 |
| Symbol master / specs | `INTERNAL` versionado | Data/Market | histórico de versiones mientras dure la oferta | Cambios con PR + `valid_from`; consumidores (`trading`, `risk`, UI) notificados por `market.symbols.changed` |
| Datos sintéticos | `INTERNAL`, etiquetado `simulated` | Trading/Tech + Head of Data | serie completa (auditoría de seed) | Metodología publicable al usuario; parámetros auditables |
| Datos de sesión/estado de mercado | `INTERNAL` | Data/Market | 1 año | Calendarios versionados; efectos retroactivos prohibidos |
| Metadatos de proveedor (config, latencias, errores) | `INTERNAL` | Market Data Tech Lead | 90 días | Sin credenciales ni claves en config ni en logs (secretos solo en env/Vault) |

Reglas: (1) **no se afirma ninguna licencia** — todo rollo/redistribución figura como `REQUIERE CONTRATO`; (2) lineage de cada tick (`source`, `adapter_version`, `recv_ts`) para trazabilidad; (3) calidad y frescura con SLO medidos (`M-tech-stack`); (4) minimización: solo los campos canónicos de §2, sin PII ni datos de usuario en el pipeline de market data; (5) retención y purge por job con métrica; (6) auditoría de cambios de symbol master y de parámetros sintéticos (§5.3).

---

## 8. Plan de implementación por fases

| Fase | Qué se implementa | Estado esperado |
|---|---|---|
| **Fase 1** (foundation) | **Estructura y contratos**: Protocols de §1.1 como código tipado + DTOs canónicos en `packages/platform-contracts` + **adapter mock determinista etiquetado `MOCK`/`simulated: true`** (seed, sin red) + validadores de §2 + settings de provider (placeholders `REQUIERE PROVEEDOR`) + tests de contrato. **Sin** servicio `market-data` desplegado, sin hub WS, sin persistencia de series (el servicio opera desde Fase 3, `00-decisions` §3) | `MOCK` / `IMPLEMENTADO` (contratos) |
| **Fase 3** (market data) | Servicio `market-data`: adapters reales **solo con contrato + credenciales vigentes** (antes: mock), normalizador, Redpanda (`market.*`), persistencia TimescaleDB con huecos explícitos, symbol master + horarios/suspensiones, hub WS (`ticks`/`candles`), REST §4.3, backfill/reconciliación, calidad §6, benchmarks (`BUILD-026`…`BUILD-032`), charting sobre el histórico propio | `REQUIERE PROVEEDOR` para lo externo; `IMPLEMENTADO` para lo propio |
| **Fase 4** (trading/risk) | Consumo estable: quote interna para margen/orden, marcas para PnL y SL/TP, precios como referencia del EMS simulado; bloqueo ante `PRICE_UNAVAILABLE`/`stale` en camino crítico | `PARCIAL` (sobre feed mock/sintético) |
| **Fase 5+** | **Synthetic Market Engine** completo (§5): configuración, seed management, gate estadístico, perfiles DEV/PROD, `BUILD-046`; replays históricos, más asset classes, sandbox API/WS (`BUILD-052`) | Simulación etiquetada; oferta real solo con licencia |
| **Fase 9** (live) | Activación de fuentes externas: gate `X-07` (contrato + redistribución + 2 proveedores + failover probado) y gating `live_trading`; sin licencia, nada cambia de estado | `REQUIERE LICENCIA/REGULACIÓN` |

---

## 9. Pendientes / No determinado

| Tema | Estado |
|---|---|
| Proveedor(es) de feed y contrato de redistribución | `REQUIERE PROVEEDOR` + `REQUIERE CONTRATO` (`X-blocked-to-live` X-07); **no se selecciona proveedor en Fase 0** |
| TimescaleDB managed vs self-hosted | `DECIDIR` (`D-domain-map`) |
| Retención real de ticks (2 años) vs. coste | `DECIDIR` Fase 3 con métricas de volumen |
| Schema registry formal (JSON/Avro/Protobuf) para topics `market.*` | `DECIDIR` Fase 3 (mismo criterio que `P` §6) |
| Hub WS distribuido vs. único (afecta `seq` por topic) | `DECIDIR` Fase 3 (`R` §8) |
| Corrección de ajustes corporativos y ajustes por dividendos en equities | `PENDIENTE` hasta tener proveedor con corporate actions |
| Oferta de opciones/contratos | `REQUIERE LICENCIA/REGULACIÓN`; solo si es legalmente admisible por jurisdicción |
| Publicación de metodología sintética al usuario (transparencia) | `PENDIENTE` Fase 5 (junto con `BUILD-046`) |

---

*Fin del documento K-market-data-architecture.md*
