"""Capturas del manual del Clasificador de archivos, con datos inventados (nunca documentos ni asegurados reales).

Arma una copia de embudo.html con cada pantalla ya llena (vista elegida con #vista) y la fotografía con Chrome sin ventana.
Uso: python -I generar_capturas.py   -> img/*.png
"""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PERFIL = Path(r"D:\Arval\_herramientas\chrome-manual")   # fuera de C:, que está lleno

DEMO = r"""
<script>document.documentElement.setAttribute("data-theme", "light");</script>
<style>
  #avisoDb{display:none!important}
  body.solo-izq .cols > section:last-child, body.solo-der .cols > section:first-child{display:none}
  body.sin-cols .cols, body.sin-hist .wrap > section:last-of-type{display:none}
  body.sin-boca .boca, body.sin-boca .riel, body.sin-boca header{display:none}
  .cols{grid-template-columns:1fr!important}
</style>
<script>
setTimeout(() => {
  const $ = (id) => document.getElementById(id);
  const vista = location.hash.slice(1) || "inicio";
  const chip = (id, clase, t) => { $(id).className = "chip " + clase; $(id).innerHTML = `<span class="dot"></span>${t}`; };
  chip("chOcr", "ok", "Lectura: OCR local listo");
  chip("chIa", "ok", "Claude: listo");
  chip("chBase", "ok", "Asegurados: 221 · 196 clientes");
  const riel = (vals) => document.querySelectorAll("#riel .etapa").forEach((e, i) => {
    e.querySelector(".n").textContent = vals[i]; e.classList.toggle("activa", vals[i] > 0 && i > 0 && i < 5); });
  const duda = `<div class="archivo duda">
    <div class="q">¿De quién es <span>receta_whatsapp.jpg</span>?</div>
    <div class="m"><span>Receta</span><span>2026-11-03</span><span>OCR (foto)</span><span>leído: “Ma. Ejemplo Pérez”</span><span class="pill media">Media</span></div>
    <div class="m"><span>El paciente coincide con una dependiente de dos asegurados.</span></div>
    <div class="opciones">
      <button type="button" class="op"><span class="k">MARÍA EJEMPLO PÉREZ</span><span class="s">sugerido</span><span class="r">ARVAL CLIENTES · nombre casi completo</span></button>
      <button type="button" class="op"><span class="k">JORGE EJEMPLO RUIZ</span><span class="s"></span><span class="r">SAYER CLIENTES · relacionado: MARÍA EJEMPLO</span></button>
    </div>
    <input type="search" placeholder="Buscar otro: nombre, RFC, póliza o dependiente">
    <div class="campos"><label>Tipo <select><option>Receta</option></select></label><label>Fecha <input type="date" value="2026-11-03"></label></div>
    <details class="mas" ${vista === "opciones" ? "open" : ""}><summary>Otras opciones</summary>
      <div class="campos"><input type="text" value="MA. EJEMPLO PÉREZ" style="flex:1 1 220px"><button class="btn sec min" type="button">Es un asegurado nuevo</button></div>
      <div class="campos" style="margin-top:8px"><button class="btn sec min" type="button">No sé: mandar a _Por identificar</button>
      <button class="btn sec min" type="button">No es un documento (firma, logo, repetido): descartar</button></div>
    </details></div>`;
  const enCurso = `<div class="archivo"><div class="fila"><span class="nom">estudio_escaneado.pdf</span><span class="pill curso">leyendo</span></div><div class="barra"><span style="width:55%"></span></div></div>
    <div class="archivo"><div class="fila"><span class="nom">poliza_renovacion.pdf</span><span class="pill curso">analizando con Claude</span></div><div class="barra"><span style="width:80%"></span></div></div>
    <div class="archivo"><div class="fila"><span class="nom">factura_hospital.xml</span><span class="pill curso">en fila</span></div><div class="barra"><span style="width:5%"></span></div></div>`;
  const listo = (nom, quien, conf, tipo, fecha, por, ruta) => `<div class="archivo"><div class="fila"><span class="nom">${nom}</span>${conf ? `<span class="pill ${conf.toLowerCase()}">${conf}</span>` : ""}</div>
    <div class="m"><span><b style="color:var(--fg)">${quien}</b></span><span>${tipo}</span><span>${fecha}</span><span>${por}</span></div>
    <div class="ruta">${ruta}</div><div class="fila"><span class="muted" style="font-size:.84rem"></span><button class="btn sec min" type="button">Cambiar</button></div></div>`;
  const listos = listo("factura_farmacia.xml", "JUAN EJEMPLO LÓPEZ", "Alta", "CFDI factura", "2026-11-02", "RFC", "ARVAL CLIENTES / JUAN EJEMPLO LÓPEZ / evento abierto o nuevo / 20261102_CFDI_nn.xml")
    + listo("poliza_renovacion.pdf", "JUAN EJEMPLO LÓPEZ", "Alta", "Operación de seguro (no reembolso)", "2026-10-28", "nombre completo", "ARVAL CLIENTES / JUAN EJEMPLO LÓPEZ / evento abierto o nuevo / 20261028_SEGURO_nn.pdf")
    + listo("foto_borrosa.jpg", "Sin asegurado", "", "Otro", "", "Lau (sin asegurado)", "_Por identificar / foto_borrosa.jpg");
  const historial = `<div class="tabla-scroll"><table class="t"><thead><tr><th>Archivo</th><th>Asegurado</th><th>Tipo</th><th>Decidió</th><th>Estado</th><th>Hora</th></tr></thead><tbody>
    <tr><td>factura_farmacia.xml</td><td>JUAN EJEMPLO LÓPEZ</td><td>CFDI factura</td><td>automático · RFC</td><td>en OneDrive</td><td>05 nov, 10:42</td></tr>
    <tr><td>receta_whatsapp.jpg</td><td>MARÍA EJEMPLO PÉREZ</td><td>Receta</td><td>Lau</td><td>en OneDrive</td><td>05 nov, 10:42</td></tr>
    <tr><td>foto_borrosa.jpg</td><td>—</td><td>Otro</td><td>Lau (sin asegurado)</td><td>en OneDrive</td><td>05 nov, 10:42</td></tr>
    <tr><td>informe_medico.pdf</td><td>—</td><td>Informe médico</td><td></td><td>por confirmar</td><td>05 nov, 10:40</td></tr></tbody></table></div>`;
  const b = document.body.classList;
  if (vista === "inicio") { b.add("sin-cols", "sin-hist"); riel([0,0,0,0,0,0]); }
  if (vista === "soltar") { b.add("sin-cols", "sin-hist"); document.getElementById("boca").classList.add("sobre"); riel([0,0,0,0,0,0]); }
  if (vista === "leyendo") { b.add("sin-boca", "solo-izq", "sin-hist"); $("dudas").innerHTML = '<div class="vacio">Nada que preguntar por ahora.</div>'; $("enCurso").innerHTML = enCurso; }
  if (vista === "pregunta" || vista === "opciones") { b.add("sin-boca", "solo-izq", "sin-hist"); $("dudas").innerHTML = duda; $("enCurso").innerHTML = ""; $("notaDudas").textContent = "1 por decidir"; }
  if (vista === "listos") { b.add("sin-boca", "solo-der", "sin-hist"); $("listos").innerHTML = listos; $("envio").hidden = false; $("nListos").textContent = "3"; $("notaListos").textContent = "1 sin asegurado"; }
  if (vista === "riel") { b.add("sin-cols", "sin-hist"); riel([7,1,1,1,3,1]); document.querySelector(".boca").style.display = "none"; document.querySelector("header").style.display = "none"; }
  if (vista === "historial") { b.add("sin-boca", "sin-cols"); const h = $("historial"); h.classList.remove("vacio"); h.innerHTML = historial; }
}, 1200);
</script>
"""

VISTAS = {   # vista: (ancho, alto) en píxeles CSS
    "inicio": (1180, 470), "soltar": (1180, 380), "riel": (1180, 120), "leyendo": (640, 330),
    "pregunta": (640, 560), "opciones": (640, 680), "listos": (640, 760), "historial": (1180, 260),
}


def main():
    html = (AQUI.parent / "embudo.html").read_text(encoding="utf-8")
    html = html.replace('src="marca/arval-logo.png"', f'src="{(AQUI.parent / "marca" / "arval-logo.png").as_uri()}"')
    demo = AQUI / "_demo.html"
    demo.write_text(html + DEMO, encoding="utf-8")
    (AQUI / "img").mkdir(exist_ok=True)
    PERFIL.mkdir(parents=True, exist_ok=True)
    for vista, (ancho, alto) in VISTAS.items():
        salida = AQUI / "img" / f"{vista}.png"
        subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=2", f"--user-data-dir={PERFIL}",
                        "--allow-file-access-from-files", "--virtual-time-budget=6000", f"--window-size={ancho},{alto}",
                        f"--screenshot={salida}", f"{demo.as_uri()}#{vista}"], check=True, capture_output=True, timeout=120)
        print(vista, salida.stat().st_size)
    demo.unlink()


if __name__ == "__main__":
    sys.exit(main())
