# Runbook 02 — Backup/restore de PostgreSQL 17 local (compose)

> **Fecha:** 2026-09-28 · **Ámbito: SOLO entorno local/dev.** No existen backups productivos (infra productiva `REQUIERE PROVEEDOR`; gate LIVE en `phase0/G-security-architecture.md` §11).
> **Topología real** (`infrastructure/compose/compose.yml`, `infrastructure/compose/initdb/001_databases.sql`): imagen `postgres:17-alpine`, host `:5433` → contenedor `:5432`, volumen **`pgdata`** (`/var/lib/postgresql/data`), tres bases por servicio: **`platform_identity`**, **`platform_audit`**, **`platform_gateway`**.

## 1. Backup lógico por base (procedimiento habitual)

```powershell
# Subir stack
docker compose -f infrastructure/compose/compose.yml up -d postgres

# Dump de cada base (añadir fecha al nombre en uso real)
docker compose -f infrastructure/compose/compose.yml exec postgres pg_dump -U platform -d platform_identity -Fc -f /tmp/platform_identity.dump
docker compose -f infrastructure/compose/compose.yml exec postgres pg_dump -U platform -d platform_audit -Fc -f /tmp/platform_audit.dump
docker compose -f infrastructure/compose/compose.yml exec postgres pg_dump -U platform -d platform_gateway -Fc -f /tmp/platform_gateway.dump

# Copiar fuera del contenedor
docker compose -f infrastructure/compose/compose.yml cp postgres:/tmp/platform_identity.dump ./backups/
```

## 2. Restore

```powershell
docker compose -f infrastructure/compose/compose.yml up -d postgres

# Recrear base limpia y restaurar (ejemplo identity)
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform -c "DROP DATABASE platform_identity;"
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform -c "CREATE DATABASE platform_identity;"
docker compose -f infrastructure/compose/compose.yml cp ./backups/platform_identity.dump postgres:/tmp/restore.dump
docker compose -f infrastructure/compose/compose.yml exec postgres pg_restore -U platform -d platform_identity /tmp/restore.dump
```

> **Alternativa con `psql` desde el host** (requiere cliente PG local en `:5433`): `pg_dump -h 127.0.0.1 -p 5433 -U platform -d platform_identity -Fc -f backups/platform_identity.dump`.

## 3. Verificación post-restore (obligatoria)

```powershell
# Conectividad + conteo por schema propio (aislamiento ADR-0005)
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform_identity -c "SELECT count(*) FROM identity.users;"
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform_audit -c "SELECT count(*) FROM audit.records;"
# Migraciones al día
uv run alembic -c services/identity/alembic.ini current
# Smoke de servicios (migraciones automáticas en local/test según README)
uv run pytest
```

## 4. Caveats por servicio

| Servicio / base | Schemas/tablas clave | Caveat de restore |
|---|---|---|
| `identity` / `platform_identity` | `identity.users`, `sessions`, `email_outbox`, `outbox_events` (`published_at` NULL = pendiente), `idempotency_records`, `feature_flags` | Tras restore, el dispatcher reenvía pendientes a `audit` (dedup por `event_id` lo hace seguro). No restaurar `outbox_events` mezclando bases de distinta fecha: generaría replays masivos. |
| `audit` / `platform_audit` | `audit.records` (PK `event_id`, append-only, UPDATE/DELETE prohibidos) | Tabla inmutable: el restore debe ser completo, nunca parcial por rango (rompería la cadena forense). Verificar conteo antes/después. |
| `gateway` / `platform_gateway` | Sin tablas de dominio (stateless; estado en Redis) | Restore normalmente innecesario; Redis (`redisdata`) no se respalda aquí — tras pérdida, sesiones/denylists se reconstruyen por re-login (degradación conocida). |

**Notas:** el volumen `pgdata` solo se borra con `docker compose … down -v` (destructivo: elimina las 3 bases). `initdb/001_databases.sql` solo corre en el **primer** arranque del volumen. Backups cifrados + restore probado son gate LIVE (`G-security-architecture.md` §11.1) — en local basta este procedimiento documentado.
