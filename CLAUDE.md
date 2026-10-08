# arval-reembolsos

Automatización del organizador de reembolsos médicos del buzón de Lau (Arval México). Este repositorio lo
ejecutan rutinas de Claude en la nube y sesiones de Claude Code. Léelo completo antes de actuar.

## Qué hay aquí

- `cli.py`: comandos `selftest`, `pull`, `apply`, `resumen`, `latido`, `decisiones-locales`.
- `reembolsos/graph.py`: Microsoft Graph (OneDrive, tablas de Excel, correo) con permisos de aplicación.
- `reembolsos/catalogo.py`: catálogo de clientes y comparación de nombres (sin acentos ni mayúsculas).
- `reembolsos/clasificacion.py`: escala de confianza y prioridad, estados, lectura previa de XML y PDF con texto.
- `reembolsos/resumen.py`: correo diario ordenado por prioridad.
- `docs/`: plan, prerrequisitos, guía de ejecución, instrucciones de cada rutina.
- `panel/panel.html`: artifact "Panel de reembolsos" (base de datos compartida `db`).

## Reglas que no se negocian

1. **Datos de salud.** Los documentos contienen información médica. No los copies, resumas ni cites fuera de las
   herramientas de Arval y de este flujo de trabajo. En la conversación y en los registros solo van metadatos:
   nombre de archivo, remitente, asunto, cliente, tipo de documento. Nunca el contenido clínico.
2. **Modo.** `MODO=propone` no escribe nada en Microsoft 365: sirve para la primera semana y para pruebas.
   `MODO=aplica` mueve archivos, actualiza el Excel y envía correo. No cambies el modo por tu cuenta.
3. **Solo nombres del catálogo.** Un documento se asigna a un cliente únicamente si el nombre está en
   `trabajo/trabajo.json → catalogo`. Un nombre leído que no esté ahí va en `candidato_cliente`, nunca en `cliente`.
4. **No borres** archivos de OneDrive ni filas del Excel. Mover sí; borrar nunca.
5. **No envíes correo** salvo el resumen diario en modo aplica, y solo al destinatario configurado.
6. Si algo falla a medias, deja constancia en `trabajo/errores.txt` y registra un latido con resultado `error`.

## Cómo decide el agente (rutina Clasificador)

1. `pip install -r requirements.txt` y `python cli.py pull`.
2. Abre `trabajo/trabajo.json`. Para cada item con `requiere_lectura: true`, lee el archivo de `ruta_local` con la
   herramienta Read (PDF: primeras 3 páginas; imágenes: completas). Para los demás, el análisis previo ya trae cliente
   o motivo; revísalo solo si `preanalisis.motivo` empieza con "varios".
3. Escribe `trabajo/decisiones.json`: un objeto por `nombre_guardado` con
   `cliente` (nombre exacto del catálogo o null), `tipo_documento` (uno de `tipos_documento`),
   `identificado_por` ("nombre y RFC" | "nombre completo" | "nombre parcial" | "no identificado"),
   `candidato_cliente` (nombre leído que no está en el catálogo, o null), `rfc`, `total`, `fecha_doc`, `motivo` (una frase, sin datos clínicos).
   Documentos de operación de seguros (endosos, carátulas, finiquitos, cartas de cuentas por pagar, renovaciones) llevan
   `tipo_documento = "Operación de seguro (no reembolso)"`.
4. Antes de aplicar, trae del panel lo que Lau decidió (ver `docs/rutinas/clasificador.prompt.md`): confirmaciones de
   cliente → `trabajo/confirmaciones.json` (`[{"archivo", "cliente"}]`), altas aprobadas → `trabajo/altas.json`
   (`[{"nombre", "correo", "rfc", "alias"}]`).
5. `python cli.py apply` (toma el modo del entorno). Calcula confianza, prioridad, estado, alertas de calidad
   (RFC distinto al del catálogo, documento antiguo, CFDI sin total) y expedientes (documentos del mismo cliente en una
   ventana de 10 días, con lista de faltantes). Luego publica `trabajo/panel_snapshot.json` en la base de datos del panel
   y registra el latido: `python cli.py latido clasificador ok "<detalle>"`.
6. `python cli.py borradores`: para expedientes incompletos sin movimiento en 2 días deja en el buzón un borrador al
   cliente pidiendo lo que falta (solo en modo aplica; Lau lo revisa y lo envía ella). Nunca envíes esos correos.

## Resumen diario (rutina Resumen)

`python cli.py resumen --preparar` escribe `trabajo/resumen_datos.json`. Con esos datos escribe `trabajo/narrativa.txt`:
3 a 5 líneas en español, tono directo, para Lau: qué requiere decisión hoy, qué expedientes están atorados y por qué,
y una recomendación. Sin nombres de pacientes distintos al cliente, sin diagnósticos ni montos de salud. Después
`python cli.py resumen` arma y, en modo aplica, envía el correo con la narrativa al inicio.

## Escala

| Confianza | Cuándo | Estado | Prioridad |
| --- | --- | --- | --- |
| Alta | remitente del catálogo, o nombre completo o RFC en CFDI/texto, o nombre y RFC leídos | Recibido | 3 |
| Media | nombre completo leído por el agente, o archivo arrastrado por otro del mismo correo | Revisar | 2 |
| Baja | coincidencia parcial o varios candidatos | Revisar | 1 |
| Ninguna con candidato | nombre legible que no está en el catálogo | Cliente desconocido | 1 |
| Ninguna sin información | sin texto útil, cifrado, formato no leído | Cliente desconocido | 3 |

## Pruebas

`python -m pytest -q` (solo datos sintéticos; no hay documentos reales en el repositorio).
