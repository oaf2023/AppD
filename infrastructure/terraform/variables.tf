variable "environment" {
  description = "Entorno de despliegue (dev/staging/production). Production exige gate de fase."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment debe ser dev, staging o production."
  }
}

variable "project_name" {
  description = "Identificador del proyecto. Placeholder hasta la decisión de marca (REQUIERE DECISIÓN)."
  type        = string
  default     = "[PROJECT_NAME]"

  validation {
    condition     = length(var.project_name) > 0 && length(var.project_name) <= 64
    error_message = "project_name debe tener entre 1 y 64 caracteres."
  }
}

variable "region" {
  description = "Región del proveedor cloud. Vacío mientras no haya proveedor seleccionado (REQUIERE PROVEEDOR)."
  type        = string
  default     = ""

  validation {
    condition     = var.region == "" || length(var.region) > 0
    error_message = "region no puede ser null (usar \"\" explícito)."
  }
}
