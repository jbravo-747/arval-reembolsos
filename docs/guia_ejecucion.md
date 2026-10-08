# Guía de ejecución en la cuenta de Claude para empresas

Para Joel, con una sesión de Claude Code en la cuenta de empresa. Cada paso dice quién lo hace y cómo se comprueba.

## Paso 0. Antes de empezar (Ernesto)

Lista en `docs/prerrequisitos_ernesto.md`. No se avanza a los pasos 3 en adelante sin: credenciales de Graph, conector Microsoft 365 habilitado, confirmación sobre datos de salud.

## Paso 1. Repositorio

1. Subir este repositorio a GitHub (privado) y conectarlo en Claude Code de la cuenta de empresa.
2. En la sesión: `pip install -r requirements.txt && python -m pytest -q` → 18 pruebas en verde.

## Paso 2. Excel de control (Joel, 10 minutos)

En `Control_Reembolsos.xlsx`:

- Hoja `Registro`, tabla `tblRegistro`: comprobar que existen `Confianza` y `Enlace`; agregar `Prioridad` (escribir el encabezado a la derecha de la última columna para que entre en la tabla).
- Hoja `Clientes`, tabla `tblClientes`: columnas `Tipo`, `Alias`, `RFC` (ya existen) y poner `Tipo` a los remitentes que no son clientes.
- Hoja nueva `Monitor` con tabla `tblMonitor`: `Rutina`, `Fecha`, `Hora`, `Resultado`, `Detalle`.

## Paso 3. Verificación de Graph (Joel con Claude)

Con las variables de `.env.example` cargadas en el entorno de la sesión (nunca en el repositorio):

```
python cli.py selftest
```

Debe imprimir el drive, la carpeta base, las columnas de `tblRegistro` y `tblClientes`, y `tblMonitor: ok`. Después, en modo aplica, un `latido prueba ok` y comprobar la fila en la hoja Monitor.

## Paso 4. Panel (Joel con Claude, una sesión)

1. Pedir a Claude: "publica `panel/panel.html` como artifact con las capacidades db, user, sample y assets". El resultado es la URL del panel. `assets` es el almacén donde quedan los archivos que Lau suelta en el panel (WhatsApp, escáner) hasta que la rutina los ingresa a OneDrive y los borra de ahí.
2. Compartir el panel con Lau desde el menú Compartir de la página (nivel editar, para que pueda confirmar).
3. Sembrar datos de prueba con ArtifactData si se quiere mostrar antes de conectar: colecciones `monitor`, `pendientes`, `candidatos`, `expedientes`.
4. Guardar la URL como variable `PANEL_URL` para las rutinas.

Colecciones del panel y quién escribe:

| Colección | Escribe | Lee |
| --- | --- | --- |
| `monitor/<rutina>` | rutinas | panel (semáforo) |
| `pendientes` | rutina clasificador | panel |
| `expedientes` | rutina clasificador | panel |
| `candidatos` | rutina clasificador | panel |
| `decisiones` | panel (Lau confirma cliente) | rutina (aplica y marca `aplicada`) |
| `altas` | panel (Lau aprueba candidato) | rutina (agrega al catálogo y marca `aplicada`) |
| `solicitudes` | panel (botón Procesar ahora) | rutina (marca `atendida`) |
| `entradas` | panel (archivos soltados; el archivo va al almacén `assets`) | rutina (`cli.py ingresar`, marca `ingresado`/`clasificado`/`error` y borra el asset) |

## Paso 5. Rutina Clasificador (Joel con Claude)

1. Pedir a Claude: "crea una rutina con `docs/rutinas/rutinas.json → clasificador`, repositorio <URL>, entorno <id>, prompt de `docs/rutinas/clasificador.prompt.md`, con el conector Microsoft 365 y las variables de entorno". Claude usa la herramienta RemoteTrigger.
2. Primera semana con `MODO=propone`: la rutina clasifica y publica en el panel, pero no mueve ni escribe en Excel. Revisar con Lau la tasa de acierto en el panel.
3. Cambiar a `MODO=aplica` en el entorno de la rutina. Apagar el flujo 3 de Power Automate y dejar de usar el script local.
4. Ejecutarla a mano cuando haga falta: RemoteTrigger `run`, o botón "Procesar ahora" del panel (la siguiente corrida lo atiende).

## Paso 6. Rutina Resumen diario

Igual que el paso 5 con `docs/rutinas/rutinas.json → resumen_diario`. Primera semana en modo propone (el correo queda en `trabajo/resumen.html` y se revisa en el registro de la corrida); después aplica y se apaga el flujo 2 de Power Automate.

## Paso 7. Operación

- Lau trabaja en el panel: confirma clientes, aprueba altas, revisa expedientes con faltantes, envía los borradores que la rutina dejó en el buzón.
- Joel revisa semanalmente `tblMonitor` y el registro de corridas de las rutinas (RemoteTrigger `list_runs` / `get_run_log`).
- Cambios de reglas: editar `reembolsos/clasificacion.py` o `CLAUDE.md`, correr las pruebas, subir el cambio; las rutinas toman la versión nueva en la siguiente corrida.

## Qué hacer si algo falla

| Síntoma | Causa probable | Acción |
| --- | --- | --- |
| `selftest` falla en token | secreto vencido o permisos sin consentimiento | Ernesto renueva el secreto o concede consentimiento |
| `pull` no encuentra archivos | la carpeta se movió o cambió `RUTA_BASE` | revisar variables |
| semáforo en rojo | la última corrida terminó en error | `get_run_log` de la corrida; `trabajo/errores.txt` |
| documentos mal clasificados | catálogo incompleto o alias faltantes | aprobar candidatos en el panel, agregar alias |
| correo de resumen no llega | `MODO=propone` o `Mail.Send` sin política | revisar modo y política de acceso |
