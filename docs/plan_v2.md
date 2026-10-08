## Plan v2 (8-oct-2026): ejecución con Claude for Enterprise

Decisión de Joel: Arval contrata un plan de Claude para empresas. El objetivo es ejecutar el organizador con Claude y sus conectores, hasta entregar un **artifact** (página viva de Claude) que sea el puesto de trabajo de Lau: ver el estado, clasificar lo pendiente y disparar las acciones, sin tocar Power Automate ni Excel.

### Qué cambia y qué se conserva

| Capa | Hoy | Plan v2 |
| --- | --- | --- |
| Captura del correo (llega un correo → guardar adjuntos y registrar) | Power Automate flujo 1 | **Se conserva.** Es gratuito, reacciona en segundos y lleva semanas sin fallar. Las rutinas de Claude corren como mínimo cada hora, no sirven para capturar en tiempo real |
| Identificación del cliente y clasificación del documento | Remitente + nombre en texto + Receptor del CFDI; OCR local a mano; AI Builder sin créditos | **Claude.** Lee PDF, imágenes y XML directamente (visión incluida, sin OCR aparte ni créditos de AI Builder), extrae nombre, RFC, tipo de documento, monto y fecha, lo compara con el catálogo y asigna confianza y prioridad |
| Resumen diario | Power Automate flujo 2 (apagado) | **Rutina de Claude** a las 8:00: resumen ordenado por prioridad, redactado, enviado al correo de Lau |
| Registro y archivo | Excel `Control_Reembolsos.xlsx` + carpetas en OneDrive | **Se conservan** como fuente de verdad para Arval. Claude escribe en ellos por Microsoft Graph |
| Puesto de trabajo de Lau | Excel + OneDrive + correo | **Artifact "Panel de reembolsos"**: semáforo de automatizaciones, pendientes por prioridad, confirmación de cliente con un clic, candidatos a cliente nuevos, botón "procesar ahora", historial |
| Rezago en `_Por identificar` | Script local de OCR + flujo 3 | La misma rutina de Claude lo drena hora a hora; el script local queda como respaldo |

### Arquitectura

1. **Power Automate flujo 1** (sin cambios de fondo): captura, guarda y registra. Se le quita la identificación por texto si Claude la hace mejor, o se deja como primera pasada.
2. **Rutina "Clasificador"** (agente de Claude en la nube, cada hora en horario hábil): lee del Excel las filas con `Cliente desconocido` o `Revisar` sin confirmar, descarga cada archivo de OneDrive, lo lee con Claude, decide cliente / tipo / confianza / prioridad, mueve el archivo a `Clientes/<cliente>/<mes>`, actualiza la fila del Excel, deja el resultado en la base de datos del artifact y escribe un latido en `tblMonitor`. Lo que no puede decidir queda marcado con prioridad 1 y el nombre leído como candidato.
3. **Rutina "Resumen diario"** (8:00 L-V): toma lo pendiente, lo ordena por prioridad, redacta el correo y lo envía desde soluciones@ a Lau.
4. **Artifact "Panel de reembolsos"** (publicado desde Claude, privado para la organización):
   - Semáforo por automatización a partir de `tblMonitor` (verde / ámbar / rojo).
   - Indicadores del día y de la semana.
   - Lista de pendientes por prioridad con enlace al archivo en OneDrive, para confirmar o corregir el cliente con un clic. Las confirmaciones se guardan en la base de datos del artifact (`db`) y la siguiente corrida de la rutina las aplica (mueve, actualiza Excel, agrega al catálogo).
   - Candidatos a cliente detectados por Claude, para aprobarlos y que entren al catálogo.
   - Botón "Procesar ahora": deja una solicitud en la base de datos que la rutina atiende en su siguiente corrida (y Joel puede lanzar la rutina al instante desde Claude).
   - Opcional: "Preguntar a Claude" sobre un documento desde el panel (`sample`) y lectura directa de OneDrive con el conector de Lau (`mcp`).
5. **Catálogo de clientes**: sigue en la hoja `Clientes`; Claude propone altas y correcciones, Lau aprueba en el panel.

### Prerrequisitos (los pide Joel; los resuelve el administrador, Ernesto)

1. **Plan de Claude para empresas** con asientos para Joel y Lau, y con Claude Code / rutinas en la nube habilitadas en la organización.
2. **Datos de salud**: confirmar con Anthropic (contrato empresarial) el tratamiento de información de salud: retención cero de datos y acuerdo de confidencialidad aplicable, antes de que Claude lea expedientes. Mientras no esté confirmado, Claude solo procesa metadatos (nombres de archivo, remitentes, asunto).
3. **Conector Microsoft 365** habilitado en la organización de Claude y conectado por Lau y Joel (lectura de Outlook, OneDrive y SharePoint).
4. **Acceso de escritura a Microsoft 365 para la rutina**: registro de aplicación en Entra ID (Azure AD) con permisos de aplicación `Files.ReadWrite.All` (o `Sites.Selected` acotado al OneDrive de soluciones@), `Mail.Read` y `Mail.Send` limitados al buzón de soluciones@ mediante una política de acceso, y un secreto de cliente. El conector Microsoft 365 de Claude es de lectura; para mover archivos, escribir en Excel y enviar correo la rutina usa Microsoft Graph con esas credenciales. El secreto se guarda en la configuración del entorno de la rutina, nunca en el repositorio.
5. **Repositorio Git** (GitHub) `arval-reembolsos` para el código de las rutinas: cliente de Graph, reglas de clasificación, plantillas de resumen, pruebas. Las rutinas de Claude en la nube necesitan un repositorio.
6. Decisión de Lau sobre criterio de prioridad y lista de remitentes a ignorar (ya pedidos).

### Fases

**F0. Preparación (Ernesto + Joel, 1 semana).** Plan contratado, asientos asignados, conector Microsoft 365 habilitado, registro de aplicación en Entra ID con permisos y secreto, confirmación sobre datos de salud, repositorio creado. Criterio de salida: Claude en la nube puede leer un archivo de `_Por identificar` y escribir una celda de prueba en el Excel vía Graph.

**F1. Base de código (Joel con Claude, 2 sesiones).** En el repositorio: módulo Graph (listar carpeta, descargar, mover, crear carpeta, leer y escribir filas de tabla de Excel, enviar correo), módulo de catálogo (normalización sin acentos, alias, RFC; se migra de `ocr_por_identificar.py`), módulo de clasificación (instrucciones a Claude para extraer nombre, RFC, tipo, monto, fecha; escala de confianza Alta/Media/Baja/Ninguna y prioridad 1/2/3), módulo de resumen. Pruebas con los 66 archivos del rezago actual. Criterio de salida: el clasificador acierta en los 20 casos ya conocidos y marca correctamente los 9 parciales.

**F2. Artifact "Panel de reembolsos" (Joel con Claude, 1 sesión).** Página con `db` (estado compartido), `user` (quién confirma), opcionalmente `mcp` y `sample`. Colecciones: `monitor` (latidos), `pendientes` (documentos por confirmar), `decisiones` (lo que Lau confirmó), `candidatos` (clientes nuevos), `solicitudes` (botón procesar ahora). Se publica, se comparte con Lau y se prueba con datos sembrados por Claude.

**F3. Rutina "Clasificador" (1 sesión).** Rutina en la nube cada hora de 8:00 a 19:00 L-V con el repositorio y el conector Microsoft 365. Primera semana en modo "solo propone" (escribe en el panel, no mueve); después, modo "aplica". Latido en `tblMonitor` en cada corrida. Se apaga el flujo 3 y se retira el script local.

**F4. Rutina "Resumen diario" (media sesión).** Rutina a las 8:00 L-V que redacta y envía el resumen por prioridad. Se apaga el flujo 2.

**F5. Ciclo de Lau (2 semanas de uso).** Lau confirma en el panel; la rutina aplica; se mide tasa de acierto, tiempo en `_Por identificar` y correos sin clasificar. Se ajustan reglas y catálogo. Criterio de salida: menos del 10 % de documentos con prioridad 1 al final del día.

**F6. Opcional.** Mover también la captura a Claude (rutina + Graph con suscripción a cambios del buzón) solo si Arval quiere salir de Power Automate; no se recomienda mientras el flujo 1 funcione.

### Costos

| Concepto | Costo | Nota |
| --- | --- | --- |
| Claude para empresas | Según contrato con Anthropic (los planes de equipo se publican por asiento al mes; el plan Enterprise se cotiza) | Dos asientos: Joel y Lau |
| Consumo de las rutinas | Incluido en el plan según sus límites de uso | Unas 12 corridas diarias del clasificador y 1 del resumen, con Claude Haiku 5.5; XML, PDF con texto, Word y Excel se leen sin modelo (texto y MarkItDown), solo escaneos y fotos van a lectura visual |
| AI Builder / Power Automate Premium | USD 0 | Ya no hace falta: Claude lee los documentos |
| Power Automate flujo 1 | USD 0 | Sigue con la licencia de Microsoft 365 |
| Entra ID / Graph | USD 0 | Incluido en Microsoft 365 |

### Riesgos y cómo se cubren

- **Latencia**: las rutinas corren como mínimo cada hora; la captura sigue siendo inmediata porque la hace Power Automate. Lau ve el documento en el panel en menos de una hora.
- **Escritura en Microsoft 365**: depende del registro de aplicación en Entra ID. Si Arval no lo autoriza, el plan funciona en modo "propone" (Claude escribe en el panel y Lau aplica en OneDrive) o conserva los flujos 1, 2 y 3 como brazo de escritura alimentados por un JSON que la rutina deja en OneDrive.
- **Datos de salud**: nada se procesa con Claude hasta tener la confirmación contractual. Metadatos sí.
- **Dependencia de Joel**: las rutinas corren solas en la nube; Joel solo interviene para cambios. El panel se comparte con quien Arval decida.
- **Herramientas por confirmar en el entorno de empresa**: que las rutinas puedan escribir en la base de datos del artifact y que el conector Microsoft 365 esté disponible para la organización. Se valida en F0.

### Primeros pasos (esta semana)

1. Joel entrega a Ernesto la lista de prerrequisitos 1 a 5.
2. Joel crea el repositorio y Claude migra a él el código ya hecho (`ocr_por_identificar.py`, `generar_flujo3.py`) como base de F1.
3. Claude publica una primera versión del panel con datos de prueba para que Lau opine sobre la forma antes de conectarlo.
4. Mientras tanto siguen corriendo los flujos 1 (captura) y 3 (registro desde OCR local) y el proceso local para el rezago.
