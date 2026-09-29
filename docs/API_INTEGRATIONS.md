# API_INTEGRATIONS — Registro de integraciones externas

Fecha de creación: 2026-09-28 · Última verificación de proveedores: **2026-09-28**
Proyecto: `MonedasAR` · Marca: `MonedasAR` · Dominio: `[DOMAIN]`
Owner: Market Data Tech Lead · Steward de datos: Head of Data (`D-domain-map` §1)
Estándar: `C:\AppD\docs\standards\markdown\api-governance.md` (§85 documentación, §87 matriz, §88 matriz de datos, §89 health)
Complementa: `docs/phase0/U-external-dependencies.md` §6 · `docs/phase0/K-market-data-architecture.md`

> **Alcance de este registro**: precios de **referencia informativa** en la portada (clases Forex y Crypto). **No** es un feed para trading, margen, SL/TP ni operativa: el gate **G3 sigue bloqueado** (`X-blocked-to-live.md` X-07) y `live_trading` permanece `false`. No hay contratos, ni credenciales, ni cuentas: todos los proveedores seleccionados son **keyless** (sin API key).

---

## 1. Diagrama de acceso

```text
apps/web (portada, Server Component)
   └── GET /api/v1/market-data/overview  (gateway)
          └── services/market-data
                 ├── providers/  (normalización a OverviewQuote canónico, cache TTL, circuit breaker)
                 │      ├── frankfurter.py   ──► api.frankfurter.dev   (FX primario)
                 │      ├── ecb.py           ──► data-api.ecb.europa.eu (FX failover)
                 │      ├── kraken.py        ──► api.kraken.com        (Crypto primario)
                 │      └── coingecko.py     ──► api.coingecko.com    (Crypto failover)
                 └── REST /api/v1/market-data/overview  (snapshot con source + ts + stale)
```

Regla (`K` §1.2): el dominio solo conoce los Protocols; los proveedores viven tras el adapter. Sin adapter → sin precio publicado (**nunca precio inventado**, `K` §6.1).

## 2. Integraciones seleccionadas

| # | Proveedor | Uso | Endpoint verificado (2026-09-28) | Auth / credencial | Rate limit | Fallback | Atribución obligatoria (UI) | Docs/ToS verificados | Estado |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Frankfurter** (`frankfurter.dev`) | FX primario: paridades de referencia BCE (`providers=ecb`) | `GET https://api.frankfurter.dev/v2/rates?base=eur&quotes=usd,gbp,jpy&providers=ecb` → lista `[{date,base,quote,rate}]` ✓ (2026-09-28) | **Keyless** (sin API key) | Sin cuota numérica publicada; rate-limit anti-abuso → cache cliente ≥60 s (TTL 900 s) | → #2 (ECB directo) | `Fuente: BCE (tipos de referencia vía Frankfurter)` | `frankfurter.dev/docs` + `frankfurter.dev/license` (MIT; datos: términos del provider) ✓ | **IMPLEMENTADO** |
| 2 | **ECB Data Portal** (`data-api.ecb.europa.eu`) | FX failover: origen directo del BCE (independiente de la infra de #1) | `GET https://data-api.ecb.europa.eu/service/data/EXR/D.USD%2BGBP%2BJPY.EUR.SP00.A?format=jsondata&lastNObservations=1` → serie por moneda (separador post-dataflow `/`, `+` escapado `%2B`) ✓ | **Keyless** | Sin límite publicado; fair-use ECB → cache ≥60 s | → sin fuente FX ⇒ `unavailable` (sin precio) | `Fuente: European Central Bank` (copyright: uso libre citando fuente y con exactitud) | `ecb.europa.eu/.../disclaimer` (Copyright §: free use + cite ECB) ✓ | **IMPLEMENTADO** |
| 3 | **Kraken** (`api.kraken.com`) | Crypto primario: ticker público con bid/ask/last/24h | `GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,USDTUSD` → claves `XXBTZUSD/XETHZUSD/USDTZUSD`, precios como strings ✓ | **Keyless** (endpoints `public`) | **1 req/s por IP** (support.kraken.com, act. 2026-08-10) → cache 60 s cumple | → #4 | `Fuente: Kraken` | `docs.kraken.com/api` + `support.kraken.com/articles/206548367` (rate limits) + Trading Rules §42 (datos públicos gratuitos) ✓ | **IMPLEMENTADO** |
| 4 | **CoinGecko** (`api.coingecko.com`) | Crypto failover: precio spot + cambio 24 h | `GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=usd&include_24hr_change=true` → `bitcoin.usd` ✓ (coincide con Kraken) | **Keyless** (API pública; sin key) | Límite keyless no publicado con precisión (históricamente ~10–30 req/min) → ≤1 req/60 s vía cache | → sin fuente ⇒ `unavailable` | **Obligatoria**: `Powered by CoinGecko` / `Source: CoinGecko` (texto legible ≥10 pt; API Terms §29 + Attribution Guide) | `coingecko.com/en/api_terms` (v. 2025-09-05, §21–§29) + `brand.coingecko.com/.../attribution-guide` ✓ | **IMPLEMENTADO** |

Condiciones comunes seleccionadas:
- **Sin credenciales**: ninguna integración usa API key, token ni cuenta → cero secretos en `.env`, repo, logs o docs (U §3).
- **Uso exclusivamente informativo** en la portada, con `source`, `ts` (UTC) y marca de frescura en cada precio mostrado (`K` §2).
- **Caché obligatorio** ≥60 s en el servidor (respeta rate limits de los 4 proveedores).
- **Circuit breaker** por adapter: si falla la primaria → failover; si fallan ambas → la card muestra "dato no disponible" (nunca un precio fabricado).
- Los términos de proveedores gratuitos pueden cambiar: re-verificar `last_verified_at` periódicamente (objetivo: trimestral) y ante cualquier cambio de UI que toque la atribución.

## 3. Candidatos evaluados y DESCARTADOS (con evidencia)

| Candidato | Clase | Motivo de descartado | Evidencia (verificada 2026-09-28) |
|---|---|---|---|
| ExchangeRate-API (`open.er-api.com`) | FX | **Prohíbe redistribución**: "this license does not permit re-distribution of our data… not in any product or service that offers programmatic or automatic access to exchange rate data"; cachear es solo para uso final | `exchangerate-api.com/terms` §LICENSE + §Data Caching Policy |
| Coinbase (`api.coinbase.com/v2/prices`) | Crypto | Market Data Terms: uso "personal or research purposes" y prohibición de "Redistribute, display, or disseminate the Market Data… to any third party outside of your organization" sin consentimiento escrito | `coinbase.com/legal/market_data` §2–§3 |
| Twelve Data | FX/equities | "Redistribution of data via API or similar mechanisms requires a separate licensing agreement" (además requiere API key) | `support.twelvedata.com` (Forex API v2) |
| CoinAPI | Crypto | Display a clientes externos puede constituir redistribution → requiere licenciado | `coinapi.io/usage-policy` |
| APIs de equities/índices/ETFs/ETFs y commodities keyless aptas | Acciones/Índices/ETFs/Commodities | No se encontró candidato **keyless** con términos que permitan mostrado público con evidencia suficiente en esta fase (ver §5) | — (queda `REQUIERE PROVEEDOR` en U §2 #1/#2) |

## 4. Matriz de datos (§88)

| Clase | Símbolos (iniciales) | Fuente primaria | Fuente failover | Frescura | Persistencia | Clasificación / gobernanza |
|---|---|---|---|---|---|---|
| Forex | EUR/USD, EUR/GBP, EUR/JPY (base EUR, los 3 pares que el BCE publica actualmente; **ARS excluido**: última observación ECB 2020-10-30 y Frankfurter no lo devuelve) | Frankfurter `providers=ecb` | ECB Data Portal directo | **Diaria** (referencia BCE ~16:00 CET; `ts` = medianoche UTC) — no intradía | **Sin persistencia**: solo snapshot en memoria/cache | Dato público del originario; atribución BCE obligatoria; sin PII; retención: no aplica (no se almacena) |
| Crypto | BTC/USD, ETH/USD, USDT/USD | Kraken Ticker | CoinGecko `simple/price` | Spot cacheado (60 s) | **Sin persistencia**: snapshot en memoria/cache | Dato público del originario; atribución Kraken/CoinGecko obligatoria; sin PII; retención: no aplica |

- Cada quote expuesta lleva: `symbol`, `last` (bid/ask si el originario los da), `ts` (UTC), `source` (`PROVIDER:<id>`), `stale` (`K` §2/§6).
- Sin cálculos derivados sobre datos del BCE salvo los publicados (paridades EUR-base tal cual) → se cumple "aparecer con exactitud y citar fuente" (copyright ECB).
- Cripto: no se muestran cifras de capitalización, volumen ni métricas que no vengan directas del endpoint.

## 5. Cobertura NO activada en esta fase

| Clase (card de portada) | Estado | Motivo |
|---|---|---|
| Acciones, Índices bursátiles, ETFs | `Próximamente · Fases 3-4` | Sin candidato keyless con ToS verificados que permita mostrado público; requiere proveedor con credencial/contrato (U §2 #1) |
| Commodities | `Próximamente · Fases 3-4` | Cobertura keyless insuficiente/no verificada |
| Índices derivados 24/7 | `Próximamente · Fases 3-4` | No es API externa: es el motor sintético propio (`K` §5, Fase 5 `BUILD-046`) |

## 6. Health y observabilidad (§89)

**Implementado (2026-09-28)**: `GET /healthz` y `GET /readyz` en `services/market-data`
(logs estructurados con estado del breaker por proveedor); `/healthz` agregado del
gateway incluye `market_data`. **Pendiente** (con la Fase 3 de métricas):

| Métrica | Propósito |
|---|---|
| `md_provider_up{provider}` | Disponibilidad por adapter |
| `md_provider_latency_ms{provider,p}` | Latencia (p50/p99) por adapter |
| `md_provider_breaker_state{provider}` | Estado del circuit breaker |
| `md_cache_hit_ratio` | Efectividad del cache (rate-limit hygiene) |
| `md_quotes_stale_ratio` | Frescura expuesta al usuario |

Evento de conmutación (§91): `PRIMARY_FAILED → SECONDARY_SELECTED` con `provider` como atributo.

## 7. Variables de entorno

**Ninguna requerida** (todo keyless). No existen claves de proveedor que proteger.
Las URLs base son campos de `MarketDataSettings` (`services/market-data/src/market_data/config.py`),
sobreescribibles por env (`FRANKFURTER_BASE_URL`, `ECB_BASE_URL`, `KRAKEN_BASE_URL`,
`COINGECKO_BASE_URL`) sin secretos; TTLs y breaker también son configuración.

## 8. Riesgos y limitaciones declarados

1. **Términos free cambiantes**: re-verificación periódica obligatoria; si un proveedor endurece términos → retirar la card o cambiar de fuente (breaker), nunca seguir exponiendo sin verificar.
2. **Atribución**: incumplirla viola los ToS de CoinGecko y el copyright del BCE → la UI debe mostrar siempre la fuente junto al precio.
3. **FX diario**: no es precio "en vivo"; el copy de UI debe decir "referencia diaria" para no inducir a error (no-ficción).
4. **Sin contrato de redistribución** → alcance limitado a esta página informativa; cualquier uso extendido (widget descargable, API pública propia, trading) exige contrato (U #2, X-07).
5. **G3 bloqueado**: esta selección no cierra el gate de Fase 3 (que exige SLA, failover <500 ms con feed de ticks, histórico con redistribución y contrato).

---

*Registro generado por el workflow `api-governance` (discovery → ToS → matriz → selección). Implementación: `services/market-data` entregada 2026-09-28 (providers + failover + cache + breaker + contrato + tests + gateway público); ver `docs/component-status.md`.*
