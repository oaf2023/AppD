# ADRs — Architecture Decision Records (Z)

Fecha de creación: 2026-09-27 · Estado: todos **Aceptados** salvo indicación.

Formato: Título · Estado · Fecha · Contexto · Decisión · Consecuencias · Alternativas · Referencias.

| ADR | Título | Tema |
|---|---|---|
| [0001](ADR-0001-monorepo.md) | Monorepo | Monorepo único vs multirepo |
| [0002](ADR-0002-estrategia-de-descomposicion.md) | Estrategia de descomposición | Microservicios desde el inicio + criterios de extracción |
| [0003](ADR-0003-lenguaje-de-servicio.md) | Lenguaje de servicio | Python 3.14/FastAPI; Rust/Go solo con benchmark |
| [0004](ADR-0004-api-first-y-contratos.md) | API first y contratos | OpenAPI fuente única, contract tests, versionado |
| [0005](ADR-0005-base-de-datos-por-servicio.md) | Base de datos por servicio | Schema aislado por servicio; ledger propio |
| [0006](ADR-0006-representacion-del-dinero.md) | Representación del dinero | NUMERIC/Decimal, nunca float; reglas de redondeo |
| [0007](ADR-0007-eventos-con-outbox.md) | Eventos con outbox | Transactional outbox + Redpanda |
| [0008](ADR-0008-autenticacion-de-servicios-usuario.md) | Autenticación de usuario | JWT ≤15 min + refresh rotativo; verdad en identity/Redis |
| [0009](ADR-0009-identidad-y-ids.md) | Identidad y IDs | UUIDv7, correlation_id, causation_id |
| [0010](ADR-0010-idempotencia-primero.md) | Idempotencia primero | Idempotency-Key + hash + respuesta almacenada |
| [0011](ADR-0011-ledger-inmutable.md) | Ledger inmutable | Double-entry append-only; reversión enlaceada |
| [0012](ADR-0012-feature-flags-y-modos.md) | Feature flags y modos | Flags globales/segmento/cuenta; DEMO vs LIVE |
| [0013](ADR-0013-observabilidad-otel-first.md) | Observabilidad OTel-first | Métricas/traces/logs; sin PII ni secretos |
| [0014](ADR-0014-migraciones-expand-migrate-contract.md) | Migraciones | Alembic; expand/migrate/contract |
| [0015](ADR-0015-i18n-y-rtl-desde-el-dia-1.md) | i18n y RTL desde el día 1 | 7 idiomas, texto nunca hardcodeado |
| [0016](ADR-0016-eventos-versionados.md) | Eventos versionados | Envelope, schema_version, DLQ, idempotencia |
| [0017](ADR-0017-seguridad-zero-trust-ligera.md) | Zero Trust ligera | Gateway único, tokens de servicio, mTLS en K8s |
| [0018](ADR-0018-testing-de-invariantes-financieros.md) | Tests de invariantes financieros | Gates de CI bloqueantes |
| [0019](ADR-0019-estrategia-consistencia-cap-por-subsistema.md) | Consistencia CAP por subsistema | Fuerte para dinero, eventual para analytics |
| [0020](ADR-0020-gestion-de-secretos.md) | Gestión de secretos | env local → Vault/KMS en producción |

## Reglas

- Un cambio que invalide un ADR requiere un **nuevo ADR** (no editar retroactivamente el histórico) y actualización de `docs/phase0/00-decisions.md`.
- Numeración correlativa e irreciclable: un ADR retirado conserva su número con estado `Obsoleto`.
- Plantilla para nuevos ADRs: [TEMPLATE.md](TEMPLATE.md) (formato `ADR-NNNN — …`: Estado/Fecha/Relacionados, Contexto, Decisión, Consecuencias, Alternativas, Referencias; registrar la fila en la tabla de arriba).
