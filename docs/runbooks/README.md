# Runbooks — operación local/dev

> **Ámbito:** entorno local/dev con `docker compose -f infrastructure/compose/compose.yml` (PostgreSQL 17 en `:5433`, Redis en `:6379`, Redpanda `:19092` perfil `events`, observabilidad perfil `obs`). **Nada de lo aquí descrito aplica a producción** (no hay cluster, ni Vault/KMS, ni backups productivos — `REQUIERE PROVEEDOR`).
> **Credenciales** citadas son solo las sintéticas de desarrollo (`.env.example`); jamás pegar secretos reales en runbooks (ADR-0020).

| Runbook | Tema | Estado del sistema que opera |
|---|---|---|
| [01-outbox-redpanda.md](01-outbox-redpanda.md) | Outbox de `identity` → relay Redpanda → consumidor `audit` (DLQ, backoff) | `IMPLEMENTADO` y verificado en local **y** en el despliegue OMV (`deploy/README.md`) |
| [02-restore-postgres.md](02-restore-postgres.md) | Backup/restore PostgreSQL 17 local (volumen `pgdata`) | Solo local/dev (en OMV el volumen es `pgdata` del proyecto `platform-omv`) |
| [03-websocket.md](03-websocket.md) | **ALCANCE FUTURO (Fase 3)** — streaming WS aún inexistente; checklist de activación | `PENDIENTE` (Fase 3, BUILD-029) |

> El runbook de **despliegue/operación en servidor OMV** (puertos 40000-40100,
> actualizaciones, perfiles) vive en [`deploy/README.md`](../../deploy/README.md).

Toda alerta futura debe apuntar a su runbook (`M-tech-stack.md` §7.1: *"nunca alerta sin dashboard y runbook"*).
