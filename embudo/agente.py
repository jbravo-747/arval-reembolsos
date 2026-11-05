"""ArvalClasificador.exe: agente local del Clasificador de archivos (artifact embudo.html).

Doble clic        -> ventana de configuración: detecta la carpeta compartida Arval (OneDrive sincronizado) y Descargas,
                     se copia a %LOCALAPPDATA%\\ArvalClasificador, se registra para iniciar con Windows (sin permisos de
                     administrador), crea los accesos directos al clasificador y al panel, y arranca el vigilante.
                     Si encuentra la primera versión (ArvalEmbudo) la detiene y le quita el arranque automático.
vigilar           -> en segundo plano: cada pocos segundos busca ARVAL_EMBUDO_*.zip en las carpetas de descargas de los
                     navegadores de la PC (se detectan solas) y los acomoda en Arval.
procesar <zip>    -> acomoda un paquete y termina (pruebas).
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # reembolsos/ cuando corre desde el repositorio
from reembolsos import destino  # noqa: E402
from reembolsos.embudo import CARPETA_REGISTRO, PATRON_PAQUETE, colocar_paquete  # noqa: E402

APP = "ArvalClasificador"
APP_ANTERIOR = "ArvalEmbudo"   # nombre de la primera versión
EMBUDO_URL = "https://claude.ai/artifact/EbazgykKVh3npeP7gyHuT3"
PANEL_URL = "https://claude.ai/artifact/MWqDtpw1z7ZFojfwmtmsRs"
# Destino: carpeta Arval en la raíz del OneDrive de soluciones@ (compartida con Lau), sincronizada en esta PC
ARVAL_WEB = destino.ENLACE
DUENO_ARVAL = "soluciones_arval_com_mx"
CASA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP
CONFIG = CASA / "config.json"
BITACORA = CASA / "agente.log"
INTERVALO = 5            # segundos entre revisiones de Descargas
DIAS_PROCESADOS = 15     # días que se guardan los paquetes ya acomodados antes de borrarlos de esta PC
CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
DESCARGAS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"


def log(msg):
    CASA.mkdir(parents=True, exist_ok=True)
    with BITACORA.open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def leer_config(ruta=CONFIG):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def quitar_version_anterior():
    """La primera versión se llamaba ArvalEmbudo: se detiene y se le quita el arranque automático para que no haya
    dos vigilantes tomando los mismos paquetes. Su carpeta en LOCALAPPDATA se deja (trae su registro)."""
    subprocess.run(["taskkill", "/F", "/IM", f"{APP_ANTERIOR}.exe"], capture_output=True)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_ANTERIOR)
    except OSError:
        pass
    (carpeta_escritorio() / "Embudo de expedientes.url").unlink(missing_ok=True)


# ---------------- Detección ----------------
def carpeta_descargas():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, DESCARGAS_GUID)[0]))
    except OSError:
        return Path.home() / "Downloads"


NAVEGADORES_CHROMIUM = (r"Microsoft\Edge\User Data", r"Google\Chrome\User Data", r"BraveSoftware\Brave-Browser\User Data")


def carpetas_descarga(extra=None):
    """Todas las carpetas donde los navegadores de esta PC guardan descargas: la de Windows, la que tenga configurada cada
    perfil de Edge, Chrome y Brave, la de Firefox y una carpeta extra opcional. Así nadie tiene que escribir rutas."""
    rutas = [carpeta_descargas()]
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    for base in NAVEGADORES_CHROMIUM:
        try:
            perfiles = [p for p in (local / base).iterdir() if (p / "Preferences").is_file()]
        except OSError:
            continue
        for p in perfiles:
            try:
                pref = json.loads((p / "Preferences").read_text(encoding="utf-8", errors="replace"))
                d = (pref.get("download") or {}).get("default_directory")
                if d:
                    rutas.append(Path(os.path.expandvars(d)))
            except (OSError, ValueError, AttributeError):
                pass
    try:
        for prefs in (Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles").glob("*/prefs.js"):
            texto = prefs.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'user_pref\("browser\.download\.dir",\s*"(.+?)"\);', texto)
            if m and 'browser.download.folderList", 2' in texto:
                rutas.append(Path(m[1].replace("\\\\", "\\")))
    except OSError:
        pass
    if extra:
        rutas.append(Path(extra))
    vistos, salida = set(), []
    for r in rutas:
        clave = str(r).rstrip("\\/").lower()
        if clave not in vistos and r.is_dir():
            vistos.add(clave); salida.append(r)
    return salida


def raices_onedrive():
    raices = []
    for var in ("OneDriveCommercial", "OneDrive"):
        if os.environ.get(var):
            raices.append(Path(os.environ[var]))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts") as k:
            i = 0
            while True:
                try:
                    cuenta = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, cuenta) as c:
                        raices.append(Path(winreg.QueryValueEx(c, "UserFolder")[0]))
                except OSError:
                    pass
    except OSError:
        pass
    raices += [p for p in Path.home().iterdir() if p.is_dir() and p.name.lower().startswith("onedrive")]
    vistos, salida = set(), []
    for r in raices:
        if r.exists() and str(r).lower() not in vistos:
            vistos.add(str(r).lower()); salida.append(r)
    return salida


def montajes_soluciones():
    """Carpetas que el cliente de OneDrive sincroniza desde el OneDrive de soluciones@ (botón «Sincronizar»)."""
    salida = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SyncEngines\Providers\OneDrive") as k:
            i = 0
            while True:
                try:
                    nombre = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, nombre) as c:
                        url = str(winreg.QueryValueEx(c, "UrlNamespace")[0]).lower()
                        montaje = Path(winreg.QueryValueEx(c, "MountPoint")[0])
                except OSError:
                    continue
                if DUENO_ARVAL in url:
                    salida.append(montaje)
    except OSError:
        pass
    return salida


def candidatas_arval():
    """Copias locales de la carpeta Arval de soluciones@, la mejor primero: la sincronizada desde soluciones@, luego un
    acceso directo «Arval» dentro del OneDrive de trabajo, y al final cualquier carpeta Arval de otro OneDrive."""
    puntos = {}
    for m in montajes_soluciones():
        for p in (m, m / "Arval"):
            if p.name.lower() == "arval":
                puntos[p] = 3
    for raiz in raices_onedrive():
        trabajo = raiz.name.lower().startswith("onedrive - ") or str(raiz).lower() == os.environ.get("OneDriveCommercial", "").lower()
        try:
            posibles = [raiz / "Arval", *[(q / "Arval") for q in raiz.iterdir() if q.is_dir()]]
        except OSError:
            continue
        for p in posibles:
            puntos.setdefault(p, 2 if trabajo else 0)
    salida = []
    for p, n in puntos.items():
        try:
            if not p.is_dir():
                continue
            # La marca oficial manda; luego, señales de que es la compartida: el programa, el registro o las carteras
            n += 10 * destino.es_oficial(p)
            n += any((p / x).exists() for x in (f"{APP}.exe", CARPETA_REGISTRO)) or any("CLIENTES" in q.name.upper() for q in p.iterdir() if q.is_dir())
        except OSError:
            continue
        salida.append((n, p))
    return [p for _, p in sorted(salida, key=lambda x: -x[0])]


# ---------------- Instalación ----------------
def exe_actual():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()


def instalar(arval, descargas=None, autoarranque=True, accesos=True):
    """descargas: carpeta extra opcional; las de los navegadores se detectan solas al vigilar."""
    CASA.mkdir(parents=True, exist_ok=True)
    arval, descargas = Path(arval), (str(Path(descargas)) if descargas else "")
    destino.exigir(arval)
    (arval / CARPETA_REGISTRO).mkdir(parents=True, exist_ok=True)   # prueba de escritura en la carpeta compartida
    prueba = arval / CARPETA_REGISTRO / ".prueba_escritura"
    prueba.write_text("ok", encoding="utf-8"); prueba.unlink()
    quitar_version_anterior()
    exe = exe_actual()
    if getattr(sys, "frozen", False):
        exe = CASA / f"{APP}.exe"
        if exe_actual() != exe:
            detener_vigilante()
            shutil.copy2(exe_actual(), exe)
    cfg = {"arval": str(arval), "descargas": descargas, "procesados": str(CASA / "procesados"), "exe": str(exe),
           "embudo_url": EMBUDO_URL, "configurado": datetime.now().isoformat(timespec="seconds")}
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    comando = f'"{exe}" vigilar' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{exe}" vigilar'
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as k:
        if autoarranque:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, comando)
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass
    if accesos:
        escritorio = carpeta_escritorio()
        for nombre, url in (("Clasificador de archivos", EMBUDO_URL), ("Panel de reembolsos", PANEL_URL)):
            try:
                (escritorio / f"{nombre}.url").write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
            except OSError:
                pass
    log(f"configurado: arval={arval} carpeta extra={descargas or 'ninguna'} autoarranque={autoarranque}")
    iniciar_vigilante(exe)
    return cfg


def carpeta_escritorio():
    """Escritorio real del usuario (puede estar dentro de OneDrive si este respalda el escritorio)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
    except OSError:
        return Path.home() / "Desktop"


def iniciar_vigilante(exe):
    args = [str(exe), "vigilar"] if getattr(sys, "frozen", False) else [sys.executable, str(exe), "vigilar"]
    flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(args, creationflags=flags, close_fds=True)


def detener_vigilante():
    # Cierra solo el vigilante anterior: el .exe de un archivo corre en dos procesos (cargador y programa) y ninguno de
    # los dos de esta ventana se debe cerrar.
    subprocess.run(["taskkill", "/F", "/IM", f"{APP}.exe", "/FI", f"PID ne {os.getpid()}", "/FI", f"PID ne {os.getppid()}"], capture_output=True)


# ---------------- Vigilante ----------------
def _un_solo_vigilante():
    ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\{APP}Vigilante")
    return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def _estable(p):
    """El navegador terminó de escribir: tamaño quieto y ZIP legible."""
    try:
        t1 = p.stat().st_size; time.sleep(1); t2 = p.stat().st_size
        if t1 != t2 or t1 == 0:
            return False
        with zipfile.ZipFile(p) as zf:
            return "manifiesto.json" in zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def procesar(zip_ruta, cfg):
    zip_ruta = Path(zip_ruta)
    r = colocar_paquete(zip_ruta, cfg["arval"])
    ok = sum(1 for x in r if x["resultado"] == "colocado")
    log(f"{zip_ruta.name}: {ok} colocado(s), {len(r) - ok} error(es)")
    for x in r:
        if x["resultado"] != "colocado":
            log(f"  error {x.get('nombre')}: {x.get('detalle')}")
    procesados = Path(cfg["procesados"]); procesados.mkdir(parents=True, exist_ok=True)
    if ok == len(r):
        shutil.move(str(zip_ruta), str(procesados / zip_ruta.name))
    else:   # algo falló: se deja con otro nombre para revisarlo y no reintentar en bucle
        zip_ruta.rename(zip_ruta.with_name("REVISAR_" + zip_ruta.name))
    return r


def limpiar_procesados(cfg):
    limite = time.time() - timedelta(days=DIAS_PROCESADOS).total_seconds()
    for p in Path(cfg["procesados"]).glob("*.zip"):
        if p.stat().st_mtime < limite:
            p.unlink(missing_ok=True)


def vigilar(una_vez=False):
    cfg = leer_config()
    if not cfg:
        log(f"vigilar: falta configurar (abre {APP}.exe)"); return
    if not una_vez and not _un_solo_vigilante():
        return
    ultimo_aseo, sin_marca, carpetas, revisadas = 0, False, [], 0
    while True:
        try:
            # Las carpetas de descargas se vuelven a detectar cada minuto (un navegador nuevo, un cambio de carpeta)
            if time.time() - revisadas > 60:
                nuevas = carpetas_descarga(cfg.get("descargas"))
                if nuevas != carpetas:
                    log(f"vigilando {', '.join(map(str, nuevas)) or 'ninguna carpeta'} -> {cfg['arval']}")
                carpetas, revisadas = nuevas, time.time()
            # Sin la marca oficial (carpeta que dejó de sincronizarse, otra carpeta) los paquetes esperan en Descargas
            if not destino.es_oficial(cfg["arval"]):
                if not sin_marca:
                    log(f"pausado: {cfg['arval']} no tiene la marca {destino.MARCA}; los paquetes esperan en Descargas")
                sin_marca = True
            else:
                if sin_marca:
                    log("reanudado: la carpeta Arval tiene la marca de nuevo")
                sin_marca = False
            for p in sorted(x for c in carpetas for x in c.glob(PATRON_PAQUETE)) if not sin_marca else []:
                if _estable(p):
                    procesar(p, cfg)
            if time.time() - ultimo_aseo > 3600:
                limpiar_procesados(cfg); ultimo_aseo = time.time()
        except Exception as e:  # noqa: BLE001 — el vigilante no debe caerse
            log(f"error: {type(e).__name__}: {e}")
        if una_vez:
            return
        time.sleep(INTERVALO)


# ---------------- Comprobaciones e instrucciones ----------------
INSTRUCCIONES = """PASOS PARA CONFIGURAR EL CLASIFICADOR EN ESTA COMPUTADORA

ANTES (lo hace Joel con la cuenta soluciones@)
  • En OneDrive web: Arval → Administrar acceso. Laura Torres debe tener «Puede editar».
  • En la pestaña Vínculos, el enlace no debe ser «Cualquier persona con el vínculo».

1. ONEDRIVE CON LA CUENTA DE TRABAJO
  • Clic en la nube azul junto al reloj → engrane → Configuración → Cuenta.
    Debe decir ltorres@arval.com.mx.
  • Si la nube es gris, no aparece o pide iniciar sesión: menú Inicio → escribe OneDrive →
    ábrelo e inicia sesión con el correo de Arval.

2. LA CARPETA ARVAL EN ESTA COMPUTADORA
  • Pulsa «Ver Arval en la web» (con la cuenta de Arval). Si no abre: OneDrive web → Compartido → Arval.
  • Selecciona la carpeta Arval y pulsa «Agregar acceso directo a Mis archivos»
    (si no se ve, está en los tres puntos «…»).
  • En uno o dos minutos aparece en el Explorador: OneDrive - Arval › Arval,
    con la carpeta _DESTINO_OFICIAL_ARVAL dentro.
  • Si no aparece «Agregar acceso directo», falta el permiso de edición (ver ANTES).

3. SINCRONIZACIÓN AL DÍA
  • Clic en la nube azul: debe decir que los archivos están actualizados, sin pausa ni errores.
  • No hace falta «Mantener siempre en este dispositivo».

4. CONFIGURAR ESTE PROGRAMA
  • «Carpeta compartida Arval» debe ser OneDrive - Arval\\Arval. La lista de comprobación lo confirma.
  • Las carpetas de descargas de los navegadores (Edge, Chrome, Brave, Firefox) se detectan solas;
    solo si el navegador guarda en un lugar raro, elígelo en «Carpetas de descargas».
  • Deja marcadas las casillas y pulsa «Guardar e iniciar». Todo debe quedar en verde.

5. PRUEBA
  • Abre el Clasificador (acceso directo en el escritorio), suelta un documento, confirma el asegurado
    y pulsa «Guardar en OneDrive». Acepta la descarga.
  • En segundos el archivo aparece en Arval › Cartera › Cliente › Evento.
    Si no aparece, pulsa «Ver registro» en esta ventana.
  • Avisa a Joel: él confirma desde su lado que apareció la carpeta _Embudo en Arval.

Si al abrir el programa Windows avisa «Windows protegió su PC»: Más información → Ejecutar de todas formas.
"""


def cuenta_trabajo():
    """(correo, carpeta) de la cuenta de OneDrive de trabajo conectada en esta PC, o (None, None)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts") as k:
            i = 0
            while True:
                try:
                    nombre = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if not nombre.lower().startswith("business"):
                    continue
                try:
                    with winreg.OpenKey(k, nombre) as c:
                        correo = winreg.QueryValueEx(c, "UserEmail")[0]
                        carpeta = winreg.QueryValueEx(c, "UserFolder")[0]
                    if correo:
                        return correo, carpeta
                except OSError:
                    pass
    except OSError:
        pass
    return None, None


def vigilante_activo():
    h = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, f"Local\\{APP}Vigilante")   # SYNCHRONIZE
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
    return bool(h)


def arranque_registrado():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def puede_escribir(carpeta):
    prueba = Path(carpeta) / ".arval_prueba_escritura"
    try:
        prueba.write_text("ok", encoding="utf-8"); prueba.unlink()
        return True
    except OSError:
        return False


def comprobaciones(arval, descargas=None):
    """[(ok, título, detalle)] de todo lo que necesita el clasificador en esta PC; ok=None si aún no aplica."""
    correo, carpeta = cuenta_trabajo()
    a = Path(arval) if arval else None
    hay_arval = bool(a) and a.is_dir()
    oficial = hay_arval and destino.es_oficial(a)
    cfg = leer_config()
    return [
        (bool(correo) and correo.lower().endswith("@arval.com.mx"), "OneDrive con la cuenta de trabajo",
         f"{correo} · {carpeta}" if correo else "No hay una cuenta de trabajo de OneDrive conectada (paso 1)"),
        (hay_arval, "Carpeta Arval en esta computadora", str(a) if hay_arval else "No encontré la carpeta Arval sincronizada (paso 2)"),
        (oficial, "Es la Arval de soluciones@", f"Trae {destino.MARCA}" if oficial else f"Falta {destino.MARCA}: no es la correcta o no termina de sincronizar (pasos 2 y 3)"),
        (oficial and puede_escribir(a), "Permiso para guardar en Arval", "Se pudo escribir" if oficial and puede_escribir(a) else "No se puede escribir (permiso «Puede editar» o sincronización en pausa)"),
        (bool(carpetas_descarga(descargas)), "Carpetas de descargas que vigila",
         " · ".join(map(str, carpetas_descarga(descargas))) or "No encontré ninguna carpeta de descargas"),
        ((bool(cfg) and arranque_registrado()) if cfg else None, "Configurado y arranca con Windows",
         f"Configurado el {cfg['configurado'][:16].replace('T', ' ')}" if cfg else "Aún no: pulsa «Guardar e iniciar» (paso 4)"),
        (vigilante_activo() if cfg else None, "Vigilando Descargas ahora", "Activo" if vigilante_activo() else "Detenido" if cfg else "Se activa al guardar"),
    ]


# ---------------- Ventana de configuración ----------------
def ventana():
    import tkinter as tk
    from tkinter import filedialog, ttk

    cfg = leer_config()
    previo = cfg or leer_config(CASA.parent / APP_ANTERIOR / "config.json")   # carpetas elegidas en la primera versión
    raiz = tk.Tk()
    raiz.title("Arval · Clasificador de archivos")
    raiz.geometry("720x760"); raiz.minsize(620, 680)
    marco = ttk.Frame(raiz, padding=18); marco.pack(fill="both", expand=True)
    cab = ttk.Frame(marco); cab.pack(fill="x")
    ttk.Label(cab, text="Configurar el clasificador en esta computadora", font=("Segoe UI", 14, "bold")).pack(side="left")
    ttk.Button(cab, text="Ver instrucciones", command=lambda: ver_instrucciones(raiz)).pack(side="right")
    ttk.Label(marco, wraplength=670, text="Los paquetes que descargas desde el Clasificador de archivos se acomodan solos en la carpeta "
              "compartida Arval de OneDrive (Cartera / Cliente / Evento). Revisa las dos carpetas y pulsa Guardar e iniciar. "
              "Si algo sale en rojo, «Ver instrucciones» explica cómo arreglarlo.").pack(anchor="w", pady=(4, 12))

    candidatas = [str(p) for p in candidatas_arval()]
    v_arval = tk.StringVar(value=previo.get("arval") or (candidatas[0] if candidatas else ""))
    extra_previo = previo.get("descargas") or ""
    if extra_previo and Path(extra_previo) in carpetas_descarga():   # ya se detecta sola: no hace falta como extra
        extra_previo = ""
    v_desc = tk.StringVar(value=extra_previo)
    v_auto, v_acc = tk.BooleanVar(value=True), tk.BooleanVar(value=True)

    def fila(titulo, var, valores=None):
        if titulo:
            ttk.Label(marco, text=titulo, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        f = ttk.Frame(marco); f.pack(fill="x", pady=(2, 10))
        caja = ttk.Combobox(f, textvariable=var, values=valores or []) if valores is not None else ttk.Entry(f, textvariable=var)
        caja.pack(side="left", fill="x", expand=True)
        ttk.Button(f, text="Elegir…", command=lambda: var.set(filedialog.askdirectory(initialdir=var.get() or str(Path.home())) or var.get())).pack(side="left", padx=(6, 0))

    fila("Carpeta compartida Arval (OneDrive de soluciones@)", v_arval, candidatas)
    if not candidatas:
        ttk.Label(marco, foreground="#b26a00", wraplength=590, text="No encontré la carpeta Arval sincronizada. Pulsa «Ver Arval en la web», elige "
                  "«Agregar acceso directo a Mis archivos», espera a que aparezca en el Explorador y vuelve a abrir este programa.").pack(anchor="w", pady=(0, 8))
    else:
        oficial = destino.es_oficial(candidatas[0])
        ttk.Label(marco, foreground="#2e7d4f" if oficial else "#b26a00", wraplength=590,
                  text="Comprobado: es la carpeta Arval de soluciones@." if oficial else
                  f"Ninguna carpeta trae la marca {destino.MARCA}: no es la Arval de soluciones@ o aún no termina de sincronizar.").pack(anchor="w", pady=(0, 8))
    ttk.Label(marco, text="Carpetas de descargas", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    ttk.Label(marco, foreground="#58595b", wraplength=670, text="Se detectan solas en cada navegador (Edge, Chrome, Brave, Firefox): "
              + " · ".join(map(str, carpetas_descarga())) + ". Solo si el navegador guarda en otro lugar, elígelo aquí:").pack(anchor="w", pady=(2, 0))
    fila("", v_desc)
    ttk.Checkbutton(marco, text="Iniciar con Windows", variable=v_auto).pack(anchor="w")
    ttk.Checkbutton(marco, text="Accesos directos al clasificador y al panel en el escritorio", variable=v_acc).pack(anchor="w", pady=(0, 10))
    estado = ttk.Label(marco, wraplength=670, text=f"Estado: {'configurado el ' + cfg['configurado'][:16].replace('T', ' ') if cfg else 'sin configurar'}")
    estado.pack(anchor="w", pady=(0, 10))

    # Lista de comprobación: lo que necesita esta PC, en verde o rojo
    ttk.Label(marco, text="Lista de comprobación", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    lista = tk.Frame(marco); lista.pack(fill="x", pady=(4, 10))

    def refrescar():
        for w in lista.winfo_children():
            w.destroy()
        for i, (ok, titulo, detalle) in enumerate(comprobaciones(v_arval.get().strip(), v_desc.get().strip())):
            color, signo = ("#2e7d4f", "✔") if ok else ("#58595b", "•") if ok is None else ("#b3261e", "✖")
            tk.Label(lista, text=signo, fg=color, font=("Segoe UI", 11, "bold")).grid(row=i, column=0, sticky="nw", padx=(0, 6))
            tk.Label(lista, text=titulo, font=("Segoe UI", 9, "bold"), anchor="w").grid(row=i, column=1, sticky="w")
            tk.Label(lista, text=detalle, fg="#58595b", font=("Segoe UI", 9), anchor="w", wraplength=440, justify="left").grid(row=i, column=2, sticky="w", padx=(8, 0))
    ttk.Button(marco, text="Volver a revisar", command=refrescar).pack(anchor="w", pady=(0, 12))

    def guardar():
        a, d = Path(v_arval.get().strip()), v_desc.get().strip()
        if not a.is_dir():
            estado.config(text="La carpeta Arval no existe. Elige la carpeta sincronizada de OneDrive.", foreground="#b3261e"); return
        if d and not Path(d).is_dir():
            estado.config(text="La otra carpeta de descargas no existe; elígela de nuevo o déjala vacía.", foreground="#b3261e"); return
        if not destino.es_oficial(a):
            estado.config(foreground="#b3261e", text=f"Esta no es la carpeta Arval de soluciones@: no trae la subcarpeta {destino.MARCA}. "
                          "Pulsa «Ver Arval en la web»: la carpeta correcta la tiene. Si en la web sí aparece, espera a que OneDrive "
                          "termine de sincronizar y vuelve a intentar."); return
        try:
            instalar(a, d, v_auto.get(), v_acc.get())
        except OSError as e:
            estado.config(text=f"No pude escribir en la carpeta: {e}", foreground="#b3261e"); return
        except Exception as e:  # noqa: BLE001 — cualquier otro fallo se muestra en la ventana y queda en el registro
            log(f"error al configurar: {type(e).__name__}: {e}")
            estado.config(text=f"No se pudo configurar ({type(e).__name__}: {e}). Manda una captura de esta ventana a Joel.", foreground="#b3261e"); return
        estado.config(foreground="#2e7d4f", text=f"Listo. El agente vigila las descargas de esta PC y guarda en {a}. Ya puedes cerrar esta ventana; "
                      "seguirá trabajando en segundo plano y arrancará solo al encender la computadora.")
        raiz.after(2500, refrescar)   # el vigilante tarda un momento en arrancar

    botones = ttk.Frame(marco); botones.pack(fill="x")
    ttk.Button(botones, text="Guardar e iniciar", command=guardar).pack(side="left")
    ttk.Button(botones, text="Abrir el clasificador", command=lambda: os.startfile(EMBUDO_URL)).pack(side="left", padx=6)
    ttk.Button(botones, text="Ver Arval en la web", command=lambda: os.startfile(ARVAL_WEB)).pack(side="left", padx=(0, 6))
    ttk.Button(botones, text="Ver registro", command=lambda: os.startfile(BITACORA) if BITACORA.exists() else None).pack(side="left")
    refrescar()
    if not cfg:   # primera vez en esta PC: las instrucciones se abren solas
        raiz.after(300, lambda: ver_instrucciones(raiz))
    raiz.mainloop()


def ver_instrucciones(raiz):
    import tkinter as tk
    from tkinter import ttk
    v = tk.Toplevel(raiz)
    v.title("Instrucciones · Clasificador de archivos")
    v.geometry("760x640")
    texto = tk.Text(v, wrap="word", font=("Segoe UI", 10), padx=14, pady=12, relief="flat")
    barra = ttk.Scrollbar(v, command=texto.yview); texto.configure(yscrollcommand=barra.set)
    pie = ttk.Frame(v, padding=10); pie.pack(side="bottom", fill="x")
    barra.pack(side="right", fill="y"); texto.pack(side="left", fill="both", expand=True)
    texto.insert("1.0", INSTRUCCIONES)
    for linea, contenido in enumerate(INSTRUCCIONES.splitlines(), 1):
        if contenido and contenido == contenido.upper() and not contenido.startswith(" "):
            texto.tag_add("titulo", f"{linea}.0", f"{linea}.end")
    texto.tag_configure("titulo", font=("Segoe UI", 10, "bold"), foreground="#173a6d")
    texto.configure(state="disabled")
    ttk.Button(pie, text="Ver Arval en la web", command=lambda: os.startfile(ARVAL_WEB)).pack(side="left")
    ttk.Button(pie, text="Cerrar", command=v.destroy).pack(side="right")


def main(argv):
    if argv[:1] == ["vigilar"]:
        vigilar(una_vez="--una-vez" in argv)
    elif argv[:1] == ["procesar"] and len(argv) > 1:
        cfg = leer_config()
        for x in procesar(argv[1], cfg):
            print(x["resultado"], x.get("destino") or x.get("detalle"))
    else:
        ventana()


if __name__ == "__main__":
    main(sys.argv[1:])
