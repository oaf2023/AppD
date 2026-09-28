terraform {
  required_version = ">= 1.5.0"

  # Sin required_providers: la nube concreta es REQUIERE PROVEEDOR (ADR-0020,
  # U-external-dependencies.md). Este bloque existe para que `terraform validate`
  # verifique la estructura en CI sin descargar proveedores ni tocar estado.
}
