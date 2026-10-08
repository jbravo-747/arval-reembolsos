# Implementación en el entorno de Lau, desde el paso 0

Procedimiento completo para instalar el organizador de reembolsos en producción. Lo que hicimos en pruebas con la cuenta soluciones@ sirve de referencia, pero aquí no se asume nada: cada paso dice qué se crea, quién lo hace y cómo se comprueba. El orden está pensado para que Lau tenga valor desde el paso 3 (captura automática) aunque los pasos de Claude tarden más por licencias.

**Decisión de arquitectura (paso 0.1):** los flujos y los archivos viven en una **cuenta de servicio** (en pruebas, soluciones@arval.com.mx; en producción puede ser la misma u otra que Arval designe, por ejemplo reembolsos@arval.com.mx). El buzón de Lau redirige su correo a esa cuenta conservando copia. Así Lau conserva su bandeja intacta, el sistema no depende de su cuenta personal y la rutina de Claude escribe en un solo lugar. La variante "todo en la cuenta de Lau" está en `docs/power_automate.md`, opción B.

Nombres usados abajo: `CUENTA_SERVICIO` (p. ej. soluciones@arval.com.mx), `CORREO_LAU` (ltorres@arval.com.mx).

---

## Paso 0. Preparación (administrador + Joel, 1 a 2 días)

| # | Qué | Quién | Comprobación |
| --- | --- | --- | --- |
| 0.1 | Elegir la cuenta de servicio y confirmar que tiene licencia Microsoft 365 con Outlook, OneDrive, Excel y Power Automate (incluido en la licencia; no hace falta Premium) | Ernesto | La cuenta abre make.powerautomate.com y muestra "Mis flujos" |
| 0.2 | Acceso de Joel a esa cuenta (contraseña por canal seguro o acceso delegado) y a Power Automate con ella | Ernesto | Joel inicia sesión |
| 0.3 | Plan de Claude para empresas: asientos para Joel y Lau; Claude Code con rutinas en la nube, artifacts y conector Microsoft 365 habilitados; confirmación contractual sobre datos de salud (retención cero) | Ernesto | Joel abre claude.ai/code con la cuenta de empresa y ve "Routines" |
| 0.4 | Registro de aplicación en Entra ID `Reembolsos-Claude` con permisos de aplicación `Files.ReadWrite.All` y `Mail.Send`, consentimiento de administrador, política de acceso de Exchange limitada al buzón de la cuenta de servicio, secreto de cliente (12 meses) | Ernesto | Tenant ID, Client ID y secreto entregados a Joel por canal seguro |
| 0.5 | Repositorio `arval-reembolsos` accesible desde la cuenta de empresa (el de GitHub de Joel o uno de Arval) | Joel | `git clone` funciona y `python -m pytest -q` pasa |
| 0.6 | Catálogo inicial de clientes de Lau: nombre como aparece en facturas, RFC, correo(s), alias | Lau | Archivo o lista entregada a Joel |
| 0.7 | Lista de remitentes que no son clientes (aseguradoras, escáner, avisos) y decisión sobre documentos de operación (ignorar o guardar aparte) | Lau | Lista entregada |

Los pasos 1 a 3 solo necesitan 0.1, 0.2, 0.6 y 0.7. Los pasos 4 a 6 necesitan 0.3 a 0.5.

## Paso 1. OneDrive y Excel de la cuenta de servicio (Joel, 30 minutos)

1. Generar la plantilla del Excel desde el repositorio:
   ```bash
   cd powerautomate && python generar.py --solo-excel
   ```
   Produce `powerautomate/salida/Control_Reembolsos.xlsx` con las hojas `Clientes` (tblClientes: Correo, NombreCliente, Notas, Tipo, Alias, RFC), `Registro` (tblRegistro con Confianza, Enlace y Prioridad) y `Monitor` (tblMonitor), todas en formato texto.
2. En el OneDrive de la cuenta de servicio crear la carpeta `/Reembolsos` y dentro `Clientes` y `_Por identificar`. Subir `Control_Reembolsos.xlsx` a `/Reembolsos`.
3. Llenar `Clientes` con el catálogo del paso 0.6: una fila por correo del cliente (un cliente con dos correos son dos filas con el mismo NombreCliente). Sin espacios al final de los nombres. Remitentes del paso 0.7 con `Tipo` = Aseguradora, Escaner o Aviso.
4. Obtener los identificadores que exige el conector de Excel. Con la sesión de la cuenta de servicio, en el navegador:
   - `https://<tenant>-my.sharepoint.com/personal/<cuenta>/_api/v2.0/drive` → copiar `id` (empieza con `b!`).
   - `https://<tenant>-my.sharepoint.com/personal/<cuenta>/_api/v2.0/drive/root:/Reembolsos/Control_Reembolsos.xlsx` → copiar `id`.
   (Para soluciones@ en pruebas: `arvalcommx-my.sharepoint.com/personal/soluciones_arval_com_mx/...`.)
5. Compartir `/Reembolsos` con Lau con permiso de edición.

**Comprobación:** Lau abre el Excel desde su cuenta y ve las tres hojas; Joel tiene los dos ids anotados.

## Paso 1b. Indexar los expedientes que Lau ya tiene hechos a mano (Joel con Claude, 1 sesión)

Lau ya tiene carpetas por cliente con sus documentos. No se mueven ni se renombran: se **descubren e indexan** para que el sistema arranque conociendo a sus clientes y sus expedientes.

1. Ubicar la carpeta raíz de sus expedientes (en su OneDrive, p. ej. `/Reembolsos Lau`, o compartida con la cuenta de servicio). Si está en el OneDrive de Lau, la aplicación de Graph del paso 0.4 ya tiene permiso para leerla con `--usuario`.
2. Primera pasada, solo reporte:
   ```bash
   python cli.py indexar --ruta "/Reembolsos Lau" --usuario ltorres@arval.com.mx
   ```
   Produce `trabajo/indexacion.json` (cada carpeta y cada archivo, con el cliente deducido del nombre de la carpeta o del contenido, el tipo de documento, y si hay conflicto entre carpeta y contenido) y `trabajo/catalogo_sugerido.csv` (las carpetas cuyo nombre no está en el catálogo, listas para pegar en la hoja `Clientes` con correo y RFC).
3. Revisar con Lau el catálogo sugerido: completar correo y RFC, corregir nombres, marcar lo que no es cliente. Cargarlo en `Clientes`.
4. Segunda pasada en modo aplica: registra cada archivo en `tblRegistro` con estado `Histórico` (no aparece en el resumen ni en pendientes), cliente, tipo, enlace al archivo y confianza. Con eso los expedientes del panel incluyen lo histórico y los faltantes se calculan sobre todo lo que existe.
   ```bash
   python cli.py indexar --ruta "/Reembolsos Lau" --usuario ltorres@arval.com.mx --modo aplica
   ```
5. Los escaneos e imágenes del histórico quedan marcados `requiere_lectura`; se leen con Claude solo si Lau lo pide (son muchos y el valor es menor que en lo nuevo).

**Comprobación:** `indexacion.json` sin conflictos sin resolver; el panel muestra expedientes históricos por cliente.

Decisión pendiente para Arval: si los expedientes históricos se quedan en el OneDrive de Lau (indexados, con enlace) o se copian a `/Reembolsos/Clientes/<cliente>/<mes>` de la cuenta de servicio para tener todo junto. La copia la hace Claude por Graph en una sesión; recomendable si Lau cambiará de puesto algún día.

## Paso 2. Outlook (Joel con la sesión de la cuenta de servicio; la regla, con Lau presente)

1. En el buzón de la cuenta de servicio crear la carpeta `Duplicados - revisar` al mismo nivel que Bandeja de entrada.
2. En el buzón de Lau (outlook.office.com con su sesión): Configuración > Correo > Reenvío > activar **Redirigir a** `CUENTA_SERVICIO` con **Conservar una copia** marcada. Debe ser redirigir, no reenviar: si se reenvía, todos los correos llegan "de Lau" y el sistema no puede identificar al cliente. Si la opción de reenvío está bloqueada por políticas, el administrador crea una regla de transporte equivalente o habilita el reenvío interno para esa cuenta.
3. Si durante las pruebas existió una redirección a soluciones@ y la cuenta de servicio es otra, cambiarla aquí (una sola redirección).

**Comprobación:** Lau se envía un correo de prueba desde su celular; aparece en su bandeja y en la de la cuenta de servicio con el remitente original.

## Paso 3. Flujo 1 en Power Automate (Joel, 45 minutos)

1. Generar el paquete con los ids del paso 1.4:
   ```bash
   cd powerautomate && python generar_flujos.py "<DRIVE_ID>" "<FILE_ID>" <CORREO_LAU>
   ```
   Produce `salida/Reembolsos_1_Ingesta.zip` (y el del resumen, que no se usará).
2. Con la sesión de la cuenta de servicio: make.powerautomate.com > Mis flujos > Importar > Importar paquete (heredado) > Upload del zip > fila del flujo en **Create as new** > en las tres conexiones (Outlook, Excel Online, OneDrive) elegir o crear la conexión de la cuenta de servicio > Import. Estos clics los hace una persona: la página no responde a Claude en Chrome.
3. Abrir el flujo, acción `Mover_a_duplicados`: elegir la carpeta `Duplicados - revisar` con el selector. Guardar. Encender.
4. Variables: `varPermitirMover = false` (se queda así; con el panel no hace falta mover correos), `varCorreoOperadora = CUENTA_SERVICIO`.
5. Prueba: desde un correo externo de prueba (Gmail), enviar a `CORREO_LAU` un correo con un XML y un PDF de un cliente del catálogo. En menos de dos minutos: archivos en `Clientes/<nombre>/<aaaa-mm>` y dos filas en `Registro`. Repetir con un correo sin adjuntos: una fila `Sin documentos`.

**Comprobación:** el historial del flujo muestra ejecuciones en verde; el comprobador no marca errores.

Desde este punto Lau ya tiene captura y registro automáticos, aunque los pasos siguientes tarden.

## Paso 4. Claude: código, panel y verificación de Graph (Joel, 1 sesión)

1. En Claude Code de la cuenta de empresa: clonar el repositorio, `pip install -r requirements.txt`, `python -m pytest -q`.
2. Variables de entorno en la sesión (nunca en el repositorio): las de `.env.example` con las credenciales del paso 0.4, `M365_USUARIO=CUENTA_SERVICIO`, `CORREO_RESUMEN=CORREO_LAU`, `MODO=propone`, `ONEDRIVE_WEB_BASE` con el OneDrive de la cuenta de servicio.
3. `python cli.py selftest`: debe listar `/Reembolsos`, las columnas de `tblRegistro`, `tblClientes` y `tblMonitor: ok`.
4. Publicar el panel: pedir a Claude "publica `panel/panel.html` como artifact con las capacidades db, user, sample y assets". Sembrar `panel/semilla_ejemplo.json` para enseñárselo a Lau. Compartir el panel con Lau con permiso de edición. Guardar la URL como `PANEL_URL`.
5. Primera corrida manual: `python cli.py pull` → Claude lee los pendientes → `python cli.py apply` (modo propone) → publicar el snapshot en el panel como describe `docs/rutinas/clasificador.prompt.md`. Revisar con Lau que las propuestas tienen sentido.

**Comprobación:** el panel muestra pendientes reales con prioridad y expedientes; `tblMonitor` tiene un latido.

## Paso 5. Rutinas (Joel con Claude, media sesión)

1. Crear la rutina **Reembolsos: clasificador** con `docs/rutinas/rutinas.json` (modelo Haiku 5.5, repositorio, entorno, conector Microsoft 365, variables de entorno, prompt de `docs/rutinas/clasificador.prompt.md`). Horario: cada hora de 8:00 a 19:00 L-V.
2. Crear la rutina **Reembolsos: resumen diario** (8:00 L-V) con `docs/rutinas/resumen_diario.prompt.md`.
3. Una semana en `MODO=propone`: las rutinas publican en el panel y dejan el resumen en su registro, pero no mueven ni escriben en Excel ni envían correo. Lau confirma clientes y aprueba candidatos en el panel; se mide el acierto.
4. Borrar de la semilla los datos de ejemplo del panel (colecciones `pendientes`, `expedientes`, `candidatos`, `bitacora`, `resumen`) antes de que las rutinas publiquen datos reales.

## Paso 6. Producción (Joel, 15 minutos)

1. Cambiar `MODO=aplica` en el entorno de las dos rutinas.
2. Apagar en Power Automate los flujos 0, 2 y 3 si existían (en producción solo corre el flujo 1).
3. Primer resumen diario recibido por Lau; primer documento movido por la rutina; primer archivo soltado en el panel que llega a su carpeta.
4. Borrar las copias locales que hayan quedado de las pruebas (documentos descargados, zips).

## Paso 7. Operación y mantenimiento

- **Lau, a diario:** panel (prioridad 1 primero), confirmar clientes, aprobar candidatos, soltar archivos de WhatsApp, revisar borradores en el buzón y enviarlos.
- **Joel, semanal:** `tblMonitor` y los registros de corridas (RemoteTrigger `list_runs` / `get_run_log`); errores en `trabajo/errores.txt` de la corrida.
- **Catálogo:** nuevos clientes entran por las altas del panel; correcciones directas en la hoja `Clientes`.
- **Secreto de Graph:** renovarlo antes de los 12 meses (anotar la fecha en el calendario del administrador).
- **Cambios de reglas:** editar el repositorio, correr las pruebas, subir; las rutinas toman la versión nueva en la siguiente corrida.
- **Si cambia la persona:** la cuenta de servicio no cambia; solo la redirección del buzón nuevo y el destinatario del resumen (`CORREO_RESUMEN`).

## Paso 8 (siguiente etapa). Base de datos compartida del equipo

Cuando el organizador lo use más de una persona, la fuente de verdad pasa del Excel a listas de SharePoint en un sitio del equipo (Clientes, Documentos, Expedientes, Monitor), sin costo adicional y con permisos por rol, vistas e historial. El diseño y la migración están en `docs/base_datos_equipo.md`; el código ya trae `reembolsos/listas.py` con las mismas operaciones que usa hoy sobre Excel.

## Lista de verificación final

- [ ] 0.1 a 0.7 cumplidos
- [ ] OneDrive `/Reembolsos` con Excel completo y catálogo cargado
- [ ] Carpeta `Duplicados - revisar` y redirección de Lau activa con copia
- [ ] Flujo 1 importado, carpeta reelegida, encendido, prueba en verde
- [ ] `selftest` en verde desde Claude Code de la cuenta de empresa
- [ ] Panel publicado, compartido con Lau, `PANEL_URL` guardada
- [ ] Rutinas creadas, una semana en propone, acierto revisado con Lau
- [ ] `MODO=aplica`, flujos 0, 2 y 3 apagados, copias locales borradas
