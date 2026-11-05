"""PDF del manual del Clasificador: tema claro, preguntas frecuentes abiertas, con Chrome sin ventana.
Uso: python -I generar_pdf.py   -> Manual_Clasificador_Arval.pdf
"""
import subprocess
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PERFIL = Path(r"D:\Arval\_herramientas\chrome-manual")


def main():
    html = (AQUI / "manual.html").read_text(encoding="utf-8")
    html = html.replace('<details class="faq">', '<details class="faq" open>')
    html = html.replace("<title>", '<script>document.documentElement.setAttribute("data-theme", "light")</script>\n<title>', 1)
    html = html.replace('loading="lazy"', "")   # que todas las capturas estén cargadas al imprimir
    temporal = AQUI / "_imprimir.html"
    temporal.write_text(html, encoding="utf-8")
    salida = AQUI / "Manual_Clasificador_Arval.pdf"
    PERFIL.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([CHROME, "--headless=new", f"--user-data-dir={PERFIL}", "--allow-file-access-from-files",
                        "--virtual-time-budget=8000", "--no-pdf-header-footer", f"--print-to-pdf={salida}", temporal.as_uri()],
                       check=True, capture_output=True, timeout=180)
    finally:
        temporal.unlink(missing_ok=True)
    print(salida, salida.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
