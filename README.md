# arval-reembolsos

Organizador de reembolsos médicos del buzón de Lau (Arval México), ejecutado con Claude for Enterprise.

- **Captura**: Power Automate (flujo 1) guarda cada adjunto en OneDrive y registra el correo en `Control_Reembolsos.xlsx`. Se conserva.
- **Clasificación**: una rutina de Claude en la nube, cada hora en horario hábil, lee los documentos pendientes (PDF, imágenes, XML), decide cliente, tipo, confianza y prioridad, mueve el archivo, actualiza el Excel, arma expedientes y publica el estado en el panel.
- **Resumen diario**: otra rutina a las 8:00 redacta y envía el correo a Lau ordenado por prioridad, con narrativa y expedientes con faltantes.
- **Panel**: artifact de Claude donde Lau ve el semáforo, confirma clientes, aprueba altas al catálogo, pide procesar y pregunta en lenguaje natural.

## Mejoras que aporta resolverlo con Claude

| Mejora | Dónde |
| --- | --- |
| Lee escaneos e imágenes sin OCR aparte ni créditos de AI Builder | rutina Clasificador (herramienta Read del agente, Claude Haiku 5.5) |
| Word, Excel, PowerPoint y PDF con texto se convierten a Markdown (MarkItDown) y se resuelven sin modelo | `clasificacion.texto_markitdown` |
| Expedientes: agrupa documentos por cliente y evento, detecta faltantes (CFDI, factura PDF, receta, informe) | `reembolsos/expedientes.py` |
| Alertas de calidad: RFC distinto al del catálogo, documento antiguo, CFDI sin total | `expedientes.alertas_documento` |
| Candidatos a cliente: nombres leídos que no están en el catálogo, para aprobarlos con un clic | `catalogo.candidatos_en_texto` + panel |
| Confirmaciones y altas desde el panel que la rutina aplica (archivo, Excel y catálogo) | `cli.py apply` |
| Resumen narrativo escrito por Claude, no solo tablas | rutina Resumen + `trabajo/narrativa.txt` |
| Borradores de correo al cliente pidiendo lo que falta (Lau revisa y envía) | `cli.py borradores` |
| Pregunta al panel en lenguaje natural sobre lo pendiente | panel (`sample`) |
| Modo "propone" para operar una semana sin escribir nada en Microsoft 365 | `MODO` |

## Uso

```bash
pip install -r requirements.txt
cp .env.example .env   # solo para pruebas locales; en las rutinas las variables van en el entorno
python cli.py selftest
python cli.py pull
#   el agente lee los archivos y escribe trabajo/decisiones.json (ver CLAUDE.md)
python cli.py apply
python cli.py resumen --preparar && python cli.py resumen
python -m pytest -q
```

## Documentación

- `docs/plan_v2.md`: plan completo, fases, costos y riesgos.
- `docs/prerrequisitos_ernesto.md`: lo que debe hacer el administrador del tenant.
- `docs/implementacion_lau.md`: **procedimiento completo desde el paso 0** para instalarlo en producción en el entorno de Lau (cuenta de servicio, OneDrive y Excel, Outlook y redirección, flujo 1, Claude, rutinas, operación).
- `docs/power_automate.md`: qué se conserva de Power Automate, paquetes y generadores, y cómo pasarlo al buzón de Lau.
- `docs/guia_ejecucion.md`: pasos de la parte de Claude en la cuenta de empresa.
- `powerautomate/`: generadores de Excel y flujos y los paquetes .zip instalados hoy.
- `docs/rutinas/`: prompts y plantillas de las dos rutinas.
- `panel/panel.html`: el artifact del panel.
- `CLAUDE.md`: reglas e instrucciones para el agente.
