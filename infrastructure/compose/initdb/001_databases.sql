-- Inicialización de bases de datos por servicio (aislamiento, ADR-0005).
-- Se ejecuta solo en el primer arranque del contenedor PostgreSQL.
CREATE DATABASE platform_identity;
CREATE DATABASE platform_audit;
CREATE DATABASE platform_gateway;
CREATE DATABASE platform_ledger;
CREATE DATABASE platform_accounts;
