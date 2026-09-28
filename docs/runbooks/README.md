# Runbooks — operación local/dev

> **Ámbito:** entorno local/dev con `docker compose -f infrastructure/compose/compose.yml` (PostgreSQL 17 en `:5433`, Redis en `:6379`, Redpanda `:19092` perfil `events`, observabilidad perfil `obs`). **Nada de lo aquí descrito aplica a producción** (no hay cluster, ni Vault/KMS, ni backups productivos — `REQUIERE PROVEEDOR`).
> **Credenciales** citadas son solo las sintéticas de desarrollo (`.env.example`); jamás pegar secretos reales en runbooks (ADR-0020).

| Runbook | Tema | Estado del sistema que opera |
|---|---|---|
| [01-outbox-redpanda.md](01-outbox-redpanda.md) | Outbox de `identity` → `audit` (HTTP verificado) + relay a Redpanda (diseño `PENDIENTE`) | Dispatcher HTTP `IMPLEMENTADO`; relay Redpanda/DLQ/métricas `PENDIENTE` |
| [02-restore-postgres.md](02-restore-postgres.md) | Backup/restore PostgreSQL 17 local (volumen `pgdata`) | Solo local/dev |
| [03-websocket.md](03-websocket.md) | **ALCANCE FUTURO (Fase 3)** — streaming WS aún inexistente; checklist de activación | `PENDIENTE` (Fase 3, BUILD-029) |

Toda alerta futura debe apuntar a su runbook (`M-tech-stack.md` §7.1: *"nunca alerta sin dashboard y runbook"*).
