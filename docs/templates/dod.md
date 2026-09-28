# Definition of Done — checklist verificable

> **Origen:** criterios de `../phase0/00-decisions.md` (§§4–8), Definition of Done de las instrucciones persistentes del proyecto, `../phase0/B-requirements-matrix.md` (REQ-080), `../phase0/N-monorepo-structure.md` (§10).
> **Uso:** copiar esta checklist en la PR y marcar cada ítem con evidencia enlazada. Ítem no verificable ⇒ declarar en §8 (*Límites*), nunca marcarlo como cumplido.

## 1. Compila / ejecuta

- [ ] `uv sync --all-packages` + servicios levantan según `../../README.md` (quickstart real: `docker compose -f infrastructure/compose/compose.yml up -d postgres redis`, `uv run identity`/`gateway`/`audit`).
- [ ] Frontend (si aplica): `npm run build --workspace apps/web` verde.

## 2. Tests y calidad

- [ ] `uv run ruff check .` y `ruff format --check .` limpios.
- [ ] `uv run mypy packages services` (strict) limpio.
- [ ] `uv run pytest` verde (referencia: 52 passed en `../component-status.md`; indicar el resultado real de esta PR).
- [ ] Regla de no-ficción (`00-decisions.md` §10): nada simulado presentado como real; componentes nuevos clasificados `IMPLEMENTADO`/`PARCIAL`/`MOCK`/`PENDIENTE`/`REQUIERE PROVEEDOR`/`REQUIERE LICENCIA/REGULACIÓN`.

## 3. Diff revisado

- [ ] `git status` / `git diff` / `git log --oneline -10` inspeccionados; solo ficheros intencionales.
- [ ] Sin refactorizaciones colaterales; cambios mínimos y reversibles.
- [ ] Revisión por owner del servicio/paquete afectado.

## 4. Migraciones y contratos

- [ ] Migraciones Alembic por servicio con `upgrade`/`downgrade` verdes; schema propio, sin acceso cruzado (ADR-0005).
- [ ] Rutas nuevas en la spec del servicio propietario; `Idempotency-Key` donde sea obligatoria (`../phase0/Q-api-map.md` §1.8, ADR-0010).
- [ ] Eventos con envelope canónico e inserción en outbox en la misma transacción (ADR-0007).
- [ ] Compatibilidad: breaking ⇒ major + `Sunset` (ADR-0004). *Nota: gates automáticos de diff OpenAPI/SBOM/secret-scan son `PENDIENTE` en CI (`../component-status.md` §6) — la verificación es manual hasta entonces.*

## 5. Seguridad y datos

- [ ] Invariantes `00-decisions.md` §7: Argon2id, JWT ≤ 15 min, UUID no secuenciales, auditoría con `correlation_id`/`request_id`.
- [ ] Dinero (si aplica): `NUMERIC(38,18)` + `Decimal`, ledger como fuente de verdad, idempotencia ( `00-decisions.md` §5).
- [ ] RBAC/denegación por defecto y tests negativos donde aplique (`../phase0/G-security-architecture.md` §4).
- [ ] Política de no-logging verificada: sin passwords, tokens, secretos ni PII completa en logs/eventos (`G-security-architecture.md` §9).

## 6. Documentación viva

- [ ] `../component-status.md` actualizado si cambia el estado de un componente (REQ-076).
- [ ] ADR nuevo si se invalida una decisión (`../adr/README.md`); docs de Fase 0 y contratos actualizados si cambia comportamiento observable.

## 7. Sin secretos ni temporales

- [ ] `git diff` sin credenciales, tokens, connection strings ni valores de `.env` (solo placeholders de `.env.example`).
- [ ] Sin ficheros temporales/artefactos (`__pycache__`, `.pytest_cache`, dumps) commiteados.
- [ ] Secretos solo por entorno; nada en frontend, logs ni eventos (ADR-0020).

## 8. Límites declaradas

> Lo no verificado se declara aquí explícitamente (qué se verificó, qué no y por qué).

| Aspecto no verificado | Motivo | Seguimiento |
|---|---|---|
| … | … | … |

---

*Plantilla creada por BUILD-006 · Última revisión: 2026-09-28.*
