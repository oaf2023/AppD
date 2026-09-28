# Terraform — solo estructura (BUILD-004, REQ-071, M-tech-stack §4)

Este directorio contiene **únicamente** la estructura de IaC: `versions.tf`,
`variables.tf`, `outputs.tf` y `modules/`. El gate de CI ejecuta
`terraform init -backend=false && terraform validate`.

## Qué hay y qué no hay

| Hay | No hay (a propósito) |
|---|---|
| `required_version` de Terraform | `required_providers` / recursos — elegir nube = `REQUIERE PROVEEDOR` (`U-external-dependencies.md`, `X-blocked-to-live.md`) |
| Variables tipadas con validación (entorno, proyecto, región) | Backend remoto, estado, credenciales (ADR-0020: nada de secretos en el repo) |
| Outputs documentados | Recursos aplicados — nada se aplica en Fase 1 |
| `modules/` como contenedor para los módulos futuros | Workspaces, módulos externos (`source` remotos) |

## Reglas

1. **Nunca** commitear estado (`*.tfstate`), `*.tfvars` reales ni credenciales
   (`.gitignore` los excluye; ver ADR-0020).
2. Añadir un proveedor exige ADR/decisión de plataforma + credenciales en el
   entorno correspondiente (no en el repo).
3. `terraform validate` debe pasar en verde en `.github/workflows/ci.yml` en cada PR.
