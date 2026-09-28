output "environment" {
  description = "Entorno efectivo (derivado de las variables, sin estado remoto)."
  value       = var.environment
}

output "project_name" {
  description = "Identificador efectivo del proyecto (placeholder hasta decisión de marca)."
  value       = var.project_name
}

output "provider_status" {
  description = "Estado honesto: sin proveedor cloud asignado en Fase 1."
  value       = var.region == "" ? "REQUIERE PROVEEDOR" : "region declarada: ${var.region}"
}
