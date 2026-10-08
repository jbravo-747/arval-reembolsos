# Base de datos compartida para el equipo de Arval

Hoy la fuente de verdad es `Control_Reembolsos.xlsx` en el OneDrive de la cuenta de servicio. Funciona para una persona (Lau) con un flujo y dos rutinas escribiendo. Deja de funcionar bien cuando varias personas consultan y editan a la vez, cuando se quieren permisos distintos por rol, o cuando el histórico pasa de unas decenas de miles de filas. Este documento compara las opciones y fija el camino.

## Opciones

| Opción | Costo | Para quién | Límites | Veredicto |
| --- | --- | --- | --- | --- |
| Excel en OneDrive (actual) | 0 | 1 a 2 personas | Bloqueos al editar en paralelo; sin permisos por fila; el conector de Excel es lento con muchas filas | Mantener para arrancar |
| **Listas de SharePoint** en un sitio del equipo | 0 (incluido en Microsoft 365) | Todo el equipo | Hasta millones de elementos; vistas, filtros y permisos por lista; historial de versiones; se consulta desde Teams, Power Automate (conector estándar) y Graph | **Recomendada** como base de datos del equipo |
| Dataverse (Power Platform) | Licencias Premium por usuario | Equipos grandes con apps de Power Apps | Modelo relacional completo, pero cada usuario necesita licencia | Solo si Arval ya paga Power Apps Premium |
| Base de datos del panel (artifact `db`) | 0 | Estado operativo del panel | Tope de 5,000 documentos; no es un sistema de registro | Se queda como "memoria de trabajo" del panel, nunca como fuente de verdad |
| SQL (Azure SQL / PostgreSQL) | Suscripción de Azure | TI | Requiere administración y red | No se justifica por el volumen |

## Diseño propuesto en SharePoint

Sitio de equipo `Reembolsos` (SharePoint > sitio de grupo, con su Teams si lo quieren). Listas:

| Lista | Qué guarda | Columnas clave | Quién escribe |
| --- | --- | --- | --- |
| `Clientes` | catálogo | NombreCliente, Correo, Correos alternos, RFC, Alias, Tipo, Aseguradora, Póliza, Responsable, Activo | Lau y el equipo; la rutina (altas aprobadas) |
| `Documentos` | una fila por documento (lo que hoy es `tblRegistro`) | las mismas columnas del Excel más Cliente como búsqueda a `Clientes`, Expediente como búsqueda a `Expedientes`, Enlace, Prioridad, Confianza | flujo 1 (Power Automate), rutinas |
| `Expedientes` | un evento de reembolso por cliente | Cliente, FechaInicio, Estado (incompleto / en revisión / completo / presentado / pagado / rechazado), Faltantes, Aseguradora, Folio, MontoFacturado, MontoReembolsado, Responsable, FechaPresentación, FechaPago | rutina (crea y actualiza faltantes); el equipo (presentado, pagado, rechazado) |
| `Monitor` | latidos de las automatizaciones | Rutina, Fecha, Hora, Resultado, Detalle | rutinas |
| `Bitacora` | eventos (opcional, con retención de 90 días) | Hora, Rutina, Evento, Detalle | rutinas |

Ventajas concretas para el equipo:

- Varias personas trabajan a la vez sin bloquear un archivo.
- Permisos: el equipo edita `Expedientes`; solo Lau y Joel editan `Clientes`; `Documentos` lo escriben las automatizaciones.
- Vistas listas para usar: "Expedientes incompletos", "Presentados sin pago", "Por cliente", "Por aseguradora".
- Historial de versiones por fila: quién cambió qué y cuándo.
- Alertas de SharePoint o Power Automate a cualquiera del equipo sin tocar el código.
- El panel de Claude sigue igual: lee y escribe a través de las rutinas.

## Cómo se migra (cuando llegue el momento)

1. Crear el sitio y las cinco listas (Joel con Claude; se pueden crear por Graph con un script a partir de las columnas del Excel).
2. Dar a la aplicación `Reembolsos-Claude` el permiso `Sites.Selected` sobre el sitio (más acotado que `Sites.ReadWrite.All`).
3. Cargar el histórico: filas de `tblClientes` y `tblRegistro` a `Clientes` y `Documentos`; los expedientes se generan con `reembolsos/expedientes.py`.
4. Cambiar el flujo 1 de Power Automate para que escriba en la lista `Documentos` (conector de SharePoint, estándar) en lugar de en la tabla de Excel; el generador de paquetes se adapta.
5. En el código, `reembolsos/listas.py` ya expone las mismas tres operaciones que las tablas de Excel (leer filas, agregar, actualizar); `cli.py` elige el almacén con la variable `ALMACEN=excel|sharepoint`.
6. Una semana en paralelo (Excel y listas) y después el Excel queda de solo lectura como respaldo.

## Lo que no cambia

- Los archivos siguen en OneDrive o, mejor para un equipo, en la biblioteca de documentos del mismo sitio de SharePoint (`Reembolsos/Clientes/<cliente>/<mes>`), con los mismos nombres.
- Las rutinas de Claude y el panel no cambian de forma: solo cambia dónde leen y escriben.
- Los datos de salud nunca salen del tenant de Arval.
