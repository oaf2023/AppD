# X — Bloqueado hasta LIVE (funciones que no pueden pasar a producción)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `[PROJECT_NAME]` · Dominio: `[DOMAIN]` · Marca: `[BRAND_NAME]`

> **Propósito**: lista explícita de funciones que **NO** pueden pasar a producción hasta obtener proveedor, licencia, contrato o autorización. Es la contraparte operativa de la *regla de no-ficción* de `00-decisions.md` §10: ante la ausencia de un elemento externo **no se inventa**; se construye interface + adapter + mock + placeholder de configuración y se documenta exactamente qué falta.
> **Este documento no afirma ningún cumplimiento, ni nombre proveedores, ni licencias, ni autorizaciones.** Todas las celdas de "bloqueo" describen lo que **falta**, no lo que se tiene.

---

## 1. Etiquetas de clasificación

| Etiqueta | Significado |
|---|---|
| `REQUIERE PROVEEDOR` | Falta contrato, credenciales o integración con un tercero (pasarela, KYC, storage, mensajería, nube, custodia, feed). |
| `REQUIERE LICENCIA/REGULACIÓN` | Falta autorización, licencia, dictamen legal o aprobación de un regulador/jurisdicción. Gate duro, sin excepción. |
| `PENDIENTE` | Falta un artefacto interno o externo no clasificable arriba: evidencia, auditoría, aprobación legal de copy, drill, informe. |

> Algunas funciones acumulan etiquetas (ej. `REQUIERE PROVEEDOR + REQUIERE LICENCIA/REGULACIÓN`): se necesita **ambas**.

---

## 2. Registro de bloqueos

| # | Función | Bloqueo exacto (qué falta) | Qué se construye igualmente | Etiqueta | Fase en la que se intenta | Qué evidencia la desbloquea |
|---|---|---|---|---|---|---|
| X-01 | **LIVE trading con dinero real** (`live_trading = true`) | Licencia/autorización regulatoria por jurisdicción · acuerdo de ejecución y de liquidez · contratos de *clearing*/custodia · aprobación legal y del consejo | Código modo LIVE implementado pero **deshabilitado por defecto** con doble interlock (flag + gate de fase); modo DEMO completo; test E2E que impide activar LIVE sin evidencia del gate | `REQUIERE LICENCIA/REGULACIÓN` | Fase 9 (G9) | Licencia/autorización **vigente** + dictamen legal por escrito + contratos de ejecución/custodia firmados + sign-off del consejo documentado |
| X-02 | **Retiros reales en fiat** | Pasarela de pago o entidad bancaria con contrato · autorización aplicable para servicios de pago (o acuerdo con entidad regulada) · proveedor KYC activo para el titular · credenciales de entorno de producción | Adapter `payments` con interface + mock + sandbox; validación de límites, `Idempotency-Key`, anti-doble-pago, allowlist de destino, hold periods y flujo maker/checker ya implementados | `REQUIERE PROVEEDOR + REQUIERE LICENCIA/REGULACIÓN` | Fase 6 (G6) | Contrato de pasarela/banco firmado + evidencia de autorización aplicable + proveedor KYC aprobado en producción + prueba de retiro *end-to-end* en sandbox del proveedor |
| X-03 | **Depósitos reales en fiat** | Pasarela/banco con contrato · rails de conciliación bancaria · requisitos de autenticación fuerte que imponga el proveedor · credenciales de producción | Adapter con interface + mock; motor de conciliación ledger↔PSP con datos de prueba; eventos `DepositRequested/Completed/Failed` idempotentes; lógica de *hold* hasta liquidación | `REQUIERE PROVEEDOR` | Fase 6 (G6) | Contrato firmado + credenciales de producción + conciliación diaria al 100 % verificada durante un ciclo completo |
| X-04 | **Depósitos y retiros reales en crypto** | Proveedor de custodia o rail de red con contrato · direccionamiento de pagos · screening de direcciones · requisitos regulatorios de transferencia de activos virtuales en cada jurisdicción | Adapter con red de pruebas (*testnet*) etiquetada; confirmaciones mínimas por red como parámetro; detección de reorg con corrección por asiento de reversión; conciliación con custodio | `REQUIERE PROVEEDOR + REQUIERE LICENCIA/REGULACIÓN` | Fase 6 (G6) | Contrato de custodia firmado + evidencia regulatoria por jurisdicción + prueba de conciliación y de manejo de reorg en sandbox |
| X-05 | **Verificación KYC automática** (documento + biometría) | Contrato con proveedor de verificación de identidad · acuerdo de tratamiento de datos (DPA) · almacenamiento de documentos en producción · umbrales de decisión aceptados por compliance | Orquestador de casos KYC con interface/adapter/mock, máquina de estados y eventos `KycSubmitted/Approved/Rejected`; cola de revisión manual; clasificación de documentos y retención programada | `REQUIERE PROVEEDOR` | Fase 6 (G6) | Contrato + DPA firmados · entorno *sandbox* probado · matriz de umbrales y criterios de decisión aprobada por compliance · prueba de flujo completo |
| X-06 | **Screening de sanciones y PEP** (onboarding + monitoreo continuo) | Proveedor de listas de sanciones/PEP con contrato y **licencia de uso de los datos** · definición de umbrales y periodicidad de re-screening | Motor de reglas con listas de prueba; puntos de inserción implementados (onboarding, antes de retiro, periodicidad); eventos y casos de revisión; resultado final marcado `PENDIENTE` hasta proveedor activo | `REQUIERE PROVEEDOR` | Fase 6 (G6) | Contrato firmado + licencia de datos verificada + matriz de cobertura y umbrales aprobada por compliance + prueba de detección en sandbox |
| X-07 | **Market data real de mercados financieros** | Contrato con proveedor de feed · **derechos de redistribución** verificados legalmente · credenciales de producción · segundo proveedor para *failover* | Adapter mock + streaming WS + normalización canónica + symbol master + cache + histórico, todo sobre datos sintéticos etiquetados `SIMULADOS`; arquitectura de adapters con *failover* ya preparada | `REQUIERE LICENCIA/REGULACIÓN` (contrato + redistribución) | Fase 3 (G3) | Contrato firmado + dictamen de derechos de redistribución + credenciales de feed + prueba de *failover* <500 ms con el proveedor real |
| X-08 | **Ejecución en venue o LP externo** | Acuerdo de ejecución y de liquidez · conectividad certificada (sesión y aplicativo) · licencia correspondiente · acuerdos de *clearing* y custodia | OMS/EMS con ejecución simulada; interface de *smart order routing*; adapter FIX/REST con mock y *session stub*; framework de monitoreo de mejor ejecución preparado sin datos reales | `REQUIERE PROVEEDOR + REQUIERE LICENCIA/REGULACIÓN` | Fase 9 (G9) | Contrato de ejecución firmado + licencia vigente + certificación de conectividad aceptada + prueba de *fill* real en entorno controlado |
| X-09 | **P2P con dinero real** (escrow entre pares) | Autorización regulatoria aplicable · rail de pago para la liquidación entre pares · KYC y screening activos de ambas partes · cumplimiento AML de las transacciones P2P | Escrow lógico, liberación temporizada, disputas maker/checker, reputación y límites — todo con **dinero simulado** y etiquetado como DEMO | `REQUIERE LICENCIA/REGULACIÓN + REQUIERE PROVEEDOR` | Intento en Fase 6 (G6); dinero real solo Fase 9 (G9) | Dictamen legal por jurisdicción + contratos de rail/pago + KYC y screening activos + prueba de disputa y de liberación en sandbox |
| X-10 | **Copy trading real** (réplica con dinero de terceros) | Autorización para gestionar/replicar cuentas con fondos de terceros · acuerdo de ejecución · divulgaciones de riesgo aprobadas por legal · límites regulatorios de apalancamiento por jurisdicción | Motor de réplica con dinero simulado; cálculo de ratio de réplica, límites de exposición y *kill switch*; ranking con métricas etiquetadas como simuladas | `REQUIERE LICENCIA/REGULACIÓN` | Intento en Fase 5 (G5) en DEMO; dinero real solo Fase 9 (G9) | Dictamen legal + acuerdo de ejecución firmado + divulgaciones aprobadas + límites por jurisdicción documentados |
| X-11 | **Oferta pública de la API de trading con SLA** | Términos de API y SLA **legalmente vinculantes** aprobados · entorno público duradero con capacidad probada · soporte y escalado definidos · y, para operaciones con dinero real, la licencia de X-01 | OpenAPI 3.1, portal de desarrollador, SDKs, *sandbox* con datos sintéticos, *tiers* y rate limits, analítica de uso — todo etiquetado `sandbox`/`DEMO` sin promesa de SLA | `PENDIENTE` (+ `REQUIERE LICENCIA/REGULACIÓN` para trading real) | Fase 5 (G5) para sandbox; SLA público solo tras Fase 9 | Dictamen legal de términos y SLA + pen test sin *critical*/*high* + gates G8/G9 + capacidad y soporte probados |
| X-12 | **Toda declaración pública de licencia, regulación, segregación de fondos o seguro** | Permiso legal: solo puede afirmarse lo que se posee con evidencia · número o referencia de autorización verificable (cuando exista) · pólizas contratadas con certificado (cuando existan) · dictamen de legal sobre cada claim | Página legal con marcadores `[PROJECT_NAME]`/`[BRAND_NAME]` y secciones de claim en borrador marcadas `NO PUBLICAR`; política interna de aprobación de *copy* legal; checklist de claims | `REQUIERE LICENCIA/REGULACIÓN` | Gate continuo; verificación obligatoria antes de Fase 6 (G6) y Fase 9 (G9) | Autorización vigente + dictamen legal por escrito por cada frase + certificados de póliza o certificado de registro, según corresponda |
| X-13 | **Statements fiscales con validez legal** | Validez legal (formato, firma, jurisdicción) · datos LIVE de operaciones · aprobación fiscal/legal del modelo · proceso de emisión, entrega y conservación | Generador de reportes y estados de cuenta operativos sobre datos de prueba, con marca visible `NO VÁLIDO FISCALMENTE` y sin campos de firma fiscal | `PENDIENTE` | Reportes operativos en Fase 7; validez legal solo Fase 9 | Dictamen fiscal y legal + operaciones en modo LIVE + proceso de emisión y conservación aprobado |
| X-14 | **Llamadas a datos de cumplimiento (GDPR u otros) presentadas como hechos verificados** | Evidencia real: acuerdos de tratamiento de datos con cada tercero · registro de operaciones de tratamiento · base legal por finalidad · evaluación de impacto · registro de brechas · y, si procede, comunicación a autoridad | Inventario interno de datos y de operaciones de tratamiento, matriz de clasificación, *lineage* y política de retención — **sin ninguna afirmación externa de cumplimiento** | `PENDIENTE` | Inventario desde Fase 1 (G1); validación externa en Fase 8 (G8) | Acuerdos de tratamiento firmados + ROPA/registro completo + evaluación de impacto + dictamen de privacidad + evidencias de control |
| X-15 | **Notificaciones transaccionales reales** (email/SMS/push) | Proveedor de mensajería con contrato, credenciales y verificación de dominio/remitente | Adapter con mock, plantillas, cola, reintentos con backoff, DLQ e interfaz de entrega en la aplicación (*in-app*) | `REQUIERE PROVEEDOR` | Mock desde Fase 2; real en Fase 6 (G6) | Contrato + credenciales de producción + prueba de entregabilidad y de rebotes gestionados |
| X-16 | **Almacenamiento de documentos KYC y estados en object storage de producción** | Cuenta y contrato con proveedor de almacenamiento · región, cifrado y control de acceso configurados · cláusula de retención y borrado | Adapter local/mock, interfaces de subida, control de acceso por rol, política de retención y borrado programado | `REQUIERE PROVEEDOR` | Placeholder desde Fase 1 (G1); real en Fase 6 (G6) | Cuenta + contrato + configuración de cifrado y acceso verificada + prueba de borrado con evidencia |
| X-17 | **Secrets manager / KMS en producción** | Proveedor de gestión de secretos, credenciales, política de rotación y procedimiento *break-glass* | Variables de entorno solo en local/dev, interfaz de proveedor de secretos, *secret-scan* en CI, inventario de secretos con owner | `REQUIERE PROVEEDOR` | Local desde Fase 1 (G1); producción en Fase 8 (G8) | Cuenta + política de rotación aplicada + rotación y *break-glass* probados + cero secretos en repositorio |
| X-18 | **Reporting regulatorio** (reporte de transparencia/transacciones) | Licencia/obligación aplicable · proveedor de reporte con contrato e identificadores · aceptación del esquema y de los plazos | Pipeline de eventos versionado con retención de 7 años, almacenamiento inmutable y generación de ficheros **sin envío real** | `REQUIERE LICENCIA/REGULACIÓN + REQUIERE PROVEEDOR` | Fase 9 (G9) | Licencia vigente + contrato con el proveedor de reporte + prueba de envío aceptada por el receptor |
| X-19 | **Pen test y auditoría externa declarados** | Contratación de una firma especializada · alcance y metodología acordados · ventana de remediación | *Hardening* interno, *threat model*, escaneo de dependencias e imágenes en CI, revisiones de seguridad de código | `PENDIENTE` | Fase 8 (G8) | Informe final con 0 *critical* y 0 *high*, y evidencia de remediación de los medios |
| X-20 | **Aseguramiento externo declarado** (póliza de responsabilidad, ciber o D&O) | Contratación de la póliza y certificado vigente · cobertura revisada legalmente para la actividad real | Cláusulas de responsabilidad en documentos internos **marcadas como borrador**, sin cifras ni coberturas publicadas | `REQUIERE PROVEEDOR + PENDIENTE` | Antes de Fase 9 (G9) | Certificado de póliza vigente + dictamen legal de cobertura aplicable |

---

## 3. Reglas transversales de gating

1. **Ninguna función de la tabla anterior se activa por configuración, *feature flag* o presión de calendario.** El desbloqueo exige la evidencia de la última columna, adjunta al gate de la fase.
2. **El flag `live_trading` permanece `false`** hasta que X-01 esté desbloqueada con todas sus evidencias (`00-decisions.md` §6).
3. **El mock no se promociona como real**: todo adaptador sin proveedor expone su estado (`MOCK`, `REQUIERE PROVEEDOR`, `REQUIERE LICENCIA/REGULACIÓN`) en la documentación técnica y en la respuesta de *health*/detalle del componente.
4. **Cada desbloqueo requiere ADR o actualización de este documento**, con fecha, responsable y evidencia referenciada (contrato, dictamen, informe, prueba).
5. **Cuando un proveedor se obtenga, se evalúa el riesgo de concentración** (R-008 y R-009 en `V-risk-register.md`): un proveedor único no desbloquea por sí solo funciones críticas sin plan de *failover*.
6. **La revisión de este documento es obligatoria en cada gate de fase** y siempre que cambie una regulación, un proveedor o el alcance.

---

## 4. Qué NO se debe publicar en la web pública hasta entonces

Hasta que la evidencia correspondiente de §2 exista y legal lo apruebe por escrito, **no se publica** en la web pública, en la app, en tiendas, en redes, en prensa ni en documentación de usuario:

**4.1 Copy legal y claims regulatorios**
- Números, códigos o referencias de licencia, autorización o registro que no se posean.
- Palabras como "regulado", "autorizado", "supervisado por", "entidad supervisora", "con licencia de" aplicadas al proyecto.
- Afirmaciones de **segregación de fondos**, custodia segregada, cuentas de salvaguarda o fondos de compensación.
- Afirmaciones de **seguro** (ciber, responsabilidad, depósitos) sin póliza contratada y certificado.
- Afirmaciones de cumplimiento certificado (GDPR, SOC 2, PCI DSS, ISO u otras) presentadas como hechos verificados.
- Afirmaciones de *best execution*, de precios "de mercado" o de "ejecución en exchange/venue" cuando todo sea simulado.

**4.2 Claims comerciales y de producto**
- Que las funciones de X-02 a X-10 están "disponibles", "activas" o "en producción" mientras estén en `MOCK`/`PENDIENTE`.
- Que la API pública tiene SLA, disponibilidad garantizada o soporte 24/7 sin términos aprobados.
- Promesas de rendimiento, rentabilidad o resultados de estrategias; rentabilidades de *backtest* presentadas como reales; rendimientos pasados como garantía.
- Estadísticas (volumen transaccional, número de usuarios, activos administrados, uptime, latencia) **no medidas y verificadas** con método documentado.
- Capturas, estados de cuenta o extractos con datos simulados mostrados como si fueran reales.

**4.3 Identidad y terceros**
- Marcas, logotipos, nombres o capturas de la plataforma de referencia o de terceros (independencia legal y de identidad visual, `00-decisions.md` §2).
- Nombres de proveedores, socios, venues o bancos **antes de contrato firmado** y de autorización de uso de marca.
- Uso de `[BRAND_NAME]`, dominios o certificados TLS con marca antes de confirmar disponibilidad y registro (§1 de `00-decisions.md`).

**4.4 Proceso**
- Todo *copy* público de carácter legal, financiero o de cumplimiento pasa por **aprobación legal por escrito** y queda registrado con versión y fecha antes de publicarse.
- Cualquier página que muestre datos simulados debe indicar de forma visible que son simulados y en modo DEMO.
