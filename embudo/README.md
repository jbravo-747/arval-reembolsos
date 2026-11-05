# Clasificador de archivos

Extensión del Panel de reembolsos para lo que llega fuera del correo (WhatsApp, escáner).

- `embudo.html`: artifact https://claude.ai/artifact/EbazgykKVh3npeP7gyHuT3 (capacidades db, user, sample, downloads).
  Lee cada archivo en el navegador (CFDI, capa de texto del PDF con pdf.js, OCR local con Tesseract), pide a Claude tipo,
  fecha y asegurado, y pregunta a Lau cuando no hay confianza alta. Guarda solo metadatos en su base (`entradas`, `altas`,
  `actualizaciones`); `asegurados/lista` y `catalogo/lista` son copia de la base del panel (los sincroniza la rutina, paso 2b).
  Al pulsar «Guardar en OneDrive» descarga `ARVAL_EMBUDO_<lote>.zip` (archivos + `manifiesto.json`).
- `ocr/spa-traineddata.wasm`: diccionario de español de Tesseract (`@tesseract.js-data/spa` 4.0.0_best_int, descomprimido).
  Va con extensión `.wasm` porque el servidor de artifacts no sirve `.traineddata`. No está en git: se baja con
  `curl -L https://cdn.jsdelivr.net/npm/@tesseract.js-data/spa@1.0.0/4.0.0_best_int/spa.traineddata.gz | gzip -d > ocr/spa-traineddata.wasm`.
  Al republicar: `files: {"ocr/spa-traineddata.wasm": ...}` con `root` en esta carpeta.
- `agente.py` → `ArvalClasificador.exe`: en la PC de Lau vigila Descargas y acomoda cada paquete en la carpeta Arval sincronizada
  con OneDrive (`reembolsos/embudo.py`: evento abierto a 10 días o nuevo, nombre `AAAAMMDD_TIPO_nn`, `_Por identificar`,
  nunca sobrescribe). Registro en `Arval/_Embudo/registro.jsonl`. Doble clic abre la configuración.

Compilar (PyInstaller instalado en `D:\Arval\_herramientas\pyi`, porque C: está lleno):

```bash
cd D:/Arval/arval-reembolsos/embudo
PYTHONPATH=D:/Arval/_herramientas/pyi TMP=D:/Arval/_herramientas/tmp PYINSTALLER_CONFIG_DIR=D:/Arval/_herramientas/pyicfg python -m PyInstaller --noconfirm --onefile --windowed --name ArvalClasificador --paths .. --distpath dist --workpath build --specpath build --exclude-module pymupdf --exclude-module fitz --exclude-module markitdown --exclude-module winocr --exclude-module PIL --exclude-module openpyxl --exclude-module numpy --exclude-module requests agente.py
```

## Manual

`manual/manual.html`: artifact https://claude.ai/artifact/2HwMdE6hMMp6v8NzNZfPH2 (manual de uso con capturas, datos inventados).
Las capturas no están en git: se regeneran con `python -I manual/generar_capturas.py` (Chrome sin ventana) y
`python manual/capturar_programa.py` (ventana del .exe con Pillow; sin `-I` porque Pillow está en los paquetes de usuario).
Al republicar: `files` con `img/*.png` y `root` en `embudo/manual`.
