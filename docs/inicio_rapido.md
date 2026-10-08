# Organizador de reembolsos: inicio rápido

Repositorio: https://github.com/jbravo-747/arval-reembolsos (privado). Responsable: Joel Bravo.

## 1. Obtener el código en cualquier computadora

```bash
git clone https://github.com/jbravo-747/arval-reembolsos.git
cd arval-reembolsos
pip install -r requirements.txt
python -m pytest -q        # debe terminar con 22 passed
```

## 1b. Para implementarlo en el entorno de Lau desde cero

Seguir `docs/implementacion_lau.md`: paso 0 (cuenta de servicio, licencias, Entra ID, catálogo), 1 (OneDrive y Excel generado con `powerautomate/generar.py --solo-excel`), 2 (Outlook y redirección), 3 (flujo 1 de Power Automate), 4 (Claude y panel), 5 (rutinas en modo propone), 6 (producción), 7 (operación).

## 2. Qué se puede hacer de inmediato (sin credenciales)

- Leer `docs/guia_ejecucion.md` (pasos en la cuenta de Claude para empresas) y `docs/plan_v2.md` (plan completo).
- Publicar el panel desde la cuenta de empresa: pedir a Claude "publica `panel/panel.html` como artifact con las capacidades db, user, sample y assets" y sembrarlo con `panel/semilla_ejemplo.json` para mostrarlo a Lau.
- Preparar el Excel: columna `Prioridad` en `tblRegistro`, hoja `Monitor` con `tblMonitor` (Rutina, Fecha, Hora, Resultado, Detalle), `Tipo` en los remitentes que no son clientes.

## 3. Qué necesita el administrador del tenant

Lista completa en `docs/prerrequisitos_ernesto.md`:

1. Plan de Claude para empresas con asientos para Joel y Lau; rutinas en la nube, artifacts y conector Microsoft 365 habilitados; confirmación contractual sobre datos de salud.
2. Registro de aplicación en Entra ID (`Reembolsos-Claude`) con permisos de aplicación `Files.ReadWrite.All` y `Mail.Send`, consentimiento de administrador, política de acceso limitada al buzón de soluciones@, y un secreto de cliente entregado por canal seguro.
3. Repositorio conectado a Claude Code en la cuenta de empresa.

## 4. Primera ejecución con credenciales

Variables de entorno (ver `.env.example`): `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`, `M365_USUARIO`, `CORREO_RESUMEN`, `RUTA_BASE`, `ARCHIVO_CONTROL`, `MODO=propone`, `PANEL_URL`.

```bash
python cli.py selftest     # autentica, lista /Reembolsos, lee tblRegistro, tblClientes y tblMonitor
python cli.py pull         # baja los pendientes y arma trabajo/trabajo.json
# el agente de Claude lee los archivos y escribe trabajo/decisiones.json (ver CLAUDE.md)
python cli.py apply        # en modo propone no escribe nada en Microsoft 365
```

Después: crear las rutinas "Reembolsos: clasificador" y "Reembolsos: resumen diario" con `docs/rutinas/rutinas.json` y los prompts de `docs/rutinas/`. Primera semana en modo propone; luego `MODO=aplica` y se apagan los flujos 2 y 3 de Power Automate. El flujo 1 (captura) se conserva.

## 5. Reglas que no cambian

- Los documentos contienen datos de salud: no salen de las herramientas de Arval; en registros y conversaciones solo metadatos.
- El secreto de Graph nunca va en el repositorio ni en correos.
- Las rutinas mueven y actualizan; nunca borran ni envían correo salvo el resumen diario.

## Enlaces

- Panel (prototipo con datos de ejemplo): https://claude.ai/artifact/CHJvZUSGcv91o24mg5RWWz
- Estado y solicitudes (doc para Lau y Ernesto): https://claude.ai/artifact/DWubNDSoVCZKccVVke9LKh
