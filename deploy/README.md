# Despliegue en servidor OMV (Docker) — rango de puertos 40000-40100

Stack completo de la plataforma en un único servidor Docker (`192.168.1.200`,
hostname `sq2`, x86_64). Todos los puertos publicados caen dentro del rango
**40000-40100**.

## Mapa de puertos

| Puerto  | Servicio        | Expuesto a   | URL / uso                              |
|---------|-----------------|--------------|----------------------------------------|
| 40000   | web (Next.js)   | LAN (0.0.0.0)| **http://192.168.1.200:40000** (entrada principal) |
| 40001   | gateway (FastAPI)| LAN (0.0.0.0)| API unificada `/api/v1/...`           |
| 40002   | identity        | LAN (0.0.0.0)| API de identidad directa (diagnóstico) |
| 40003   | audit           | LAN (0.0.0.0)| API de auditoría directa (diagnóstico) |
| 40004   | market-data     | LAN (0.0.0.0)| Snapshot público de mercados (`/api/v1/market-data/overview`) |
| 40010   | PostgreSQL 17   | 127.0.0.1    | datos (túnel SSH para operaciones)     |
| 40011   | Redis 7         | 127.0.0.1    | caché/sesiones                         |
| 40012   | Redpanda 19092  | 127.0.0.1    | Kafka externo (rpk desde el servidor)  |
| 40020   | Prometheus      | 127.0.0.1    | perfil `obs`                           |
| 40021   | Grafana         | LAN (0.0.0.0)| http://192.168.1.200:40021 (admin)     |
| 40022   | Loki            | 127.0.0.1    | perfil `obs`                           |
| 40023   | Tempo           | 127.0.0.1    | perfil `obs`                           |
| 40024   | OTel Collector  | 127.0.0.1    | OTLP HTTP (perfil `obs`)               |

Los puertos de datos/obs internos se enlazan a `127.0.0.1` a propósito
(minimizar superficie de exposición en LAN; acceso vía SSH).

## Despliegue inicial

```bash
cd /opt/platform
cp deploy/.env.example deploy/.env
# Generar secretos reales (NUNCA versionar .env):
#   POSTGRES_PASSWORD, JWT_SECRET, SERVICE_TOKEN_SECRET -> openssl rand -hex 32
#   GRAFANA_PASSWORD -> contraseña fuerte
$EDITOR deploy/.env
docker compose -f deploy/compose.yml build
docker compose -f deploy/compose.yml up -d                 # núcleo
docker compose -f deploy/compose.yml --profile obs up -d   # + observabilidad
```

- Las migraciones Alembic de identity y audit se ejecutan automáticamente al
  arrancar sus contenedores (comando previo a `uvicorn`).
- `REQUIRE_EMAIL_VERIFICATION=false` en este entorno de demostración LAN: el
  registro crea cuentas operativas sin correo. Cambiar a `true` si se conecta SMTP.

## Operación

```bash
docker compose -f deploy/compose.yml ps
docker compose -f deploy/compose.yml logs -f gateway identity audit web
docker compose -f deploy/compose.yml restart web
docker compose -f deploy/compose.yml down        # para (los volúmenes persisten)
```

Actualizar tras un nuevo código: reextraer el árbol en `/opt/platform`,
`docker compose -f deploy/compose.yml build && ... up -d`.

## Seguridad

- `deploy/.env` contiene secretos reales: **no se versiona** y no se sube a git.
- `ENVIRONMENT=production` exige `JWT_SECRET`/`SERVICE_TOKEN_SECRET` reales
  (>=32 caracteres); el arranque falla si se detectan valores de desarrollo.
- El acceso de administración al servidor es SSH (root); no hay telemetría. La
  única salida a terceros es `market-data` hacia APIs públicas keyless de
  referencia (BCE/Frankfurter, Kraken/CoinGecko; sin credenciales ni datos
  personales, ver `docs/API_INTEGRATIONS.md`). La operativa real está
  desactivada (`flag_live_trading=false`).
- Grafana (40021) queda autenticado con `GRAFANA_PASSWORD` del `.env`.

## Verificación tras el despliegue

1. `docker compose -f deploy/compose.yml ps` → todos `healthy`.
2. `curl -s http://127.0.0.1:40001/healthz` → aggregate OK.
3. Navegador: `http://192.168.1.200:40000/` → landing; registro + login → `/panel`.
