# Power Automate: lo que se conserva y cómo pasarlo a la bandeja de Lau

En el Plan v2 Power Automate sigue siendo la captura: cada correo que llega se guarda en OneDrive y se registra en el Excel en segundos. Todo lo demás (clasificar, resumir, panel) lo hacen las rutinas de Claude. Este documento cubre la configuración actual, los paquetes, y el paso a producción en el buzón de Lau.

## Estado actual (8-oct-2026)

| Flujo | Cuenta | Estado | En el Plan v2 |
| --- | --- | --- | --- |
| Reembolsos - 1 Ingesta | soluciones@arval.com.mx | Encendido, `varPermitirMover = false` | **Se conserva** (captura, registro, duplicados). Su identificación por nombre queda como primera pasada; Claude corrige después |
| Reembolsos - 0 Inventario | soluciones@ | Encendido | Apagar cuando las rutinas estén en marcha; ya no aporta |
| Reembolsos - 2 Resumen diario | soluciones@ | Apagado | Lo sustituye la rutina Resumen diario; se deja apagado |
| Reembolsos - 3 Registro desde OCR local | soluciones@ | Encendido (solo corre a mano) | Lo sustituye la rutina Clasificador; apagar |
| Reembolsos - 0b Inventario retroactivo | soluciones@ | Apagado | Sin uso |

**Cómo llega el correo de Lau:** regla de redirección en el buzón de ltorres@arval.com.mx (Configuración > Correo > Reenvío, "Redirigir a" soluciones@arval.com.mx, conservando copia). Es "redirigir", no "reenviar": así el remitente original se conserva y el flujo puede identificar al cliente. Lau sigue viendo todo en su bandeja; la copia en soluciones@ es la que procesa el flujo.

## Paquetes y generadores (carpeta `powerautomate/`)

- `generar.py`: Excel de control e inventario, flujos 0 y 0b, y el empaquetador (formato "Importar paquete (heredado)").
- `generar_flujos.py`: flujos 1 y 2. Uso: `python generar_flujos.py <DRIVE_ID> <FILE_ID_CONTROL> <CORREO_RESUMEN>`.
- `generar_flujo3.py`: flujo 3 y `movidos.json`.
- `ocr_por_identificar.py`: OCR local de respaldo (Windows).
- `Reembolsos_*.zip`: los paquetes tal como están instalados hoy.

Identificadores de la cuenta soluciones@: drive `b!8avJnHscmE-rBg3j_lPOS98VyxBJXNJAjcRxNMh2oPIx-f9_vQHiR4vd1xqnwRQ7`, `Control_Reembolsos.xlsx` id `013ZAP6YESVXEOGMLWZZGZG6B734E4U7EP`, `Inventario_correos.xlsx` id `013ZAP6YFZNIFWFFQ5MVBYPTCVRJDOGWG2`. Para otra cuenta hay que obtener los suyos (el conector de Excel exige ids, no rutas).

**Reimportar un flujo** (cuando cambie el generador): Mis flujos > Importar > Importar paquete (heredado) > Upload del .zip > en la fila del flujo elegir **Update** y el flujo existente > en cada conexión elegir la de la cuenta > Import. Después del Update el flujo queda apagado: en el flujo 1 volver a elegir la carpeta `Duplicados - revisar` en la acción Mover_a_duplicados, guardar y encender. La página de importación no acepta los clics de Claude en Chrome: esos clics los hace una persona.

## Paso a producción en la bandeja de Lau

Hay dos caminos. La recomendación es **A**: mantiene todo en una cuenta de servicio que no depende de la persona, y con el Plan v2 los movimientos de duplicados en la bandeja de Lau pierden importancia porque ella trabaja desde el panel.

### Opción A (recomendada): dejar el flujo en soluciones@ y la redirección permanente

1. Confirmar que la regla de redirección de Lau sigue activa y conserva copia (ya está hecha).
2. Compartir la carpeta `/Reembolsos` del OneDrive de soluciones@ con Lau con permiso de edición (ya está compartido `Control_Reembolsos.xlsx`; falta la carpeta completa si quiere abrir archivos desde el panel sin pedir acceso).
3. Dejar `varPermitirMover = false` de forma permanente: con el Plan v2 no hace falta mover correos en la copia de soluciones@; los duplicados se marcan en el registro y en el panel.
4. Apagar los flujos 0, 2 y 3 cuando las rutinas estén en modo `aplica`.
5. Las rutinas apuntan a `M365_USUARIO=soluciones@arval.com.mx` y `CORREO_RESUMEN=ltorres@arval.com.mx` (ya es el valor por defecto en `.env.example`).

Nada de esto toca la bandeja de Lau más allá de la regla que ya existe.

### Opción B: migrar el flujo 1 al buzón de Lau

Solo si Arval exige que los archivos y el Excel vivan en el OneDrive de Lau.

1. Apagar el flujo 1 en soluciones@ (si no, cada correo se procesa dos veces).
2. En la cuenta de Lau: crear `/Reembolsos` con `Clientes` y `_Por identificar`, subir `Control_Reembolsos.xlsx` (con sus tablas y el catálogo), crear la carpeta de Outlook `Duplicados - revisar`.
3. Obtener el drive id y el file id del Excel en la cuenta de Lau (Claude lo hace desde OneDrive web con la sesión de Lau: `_api/v2.0/drive` y `…/root:/Reembolsos/Control_Reembolsos.xlsx`), regenerar el paquete con `python generar_flujos.py <DRIVE_ID_LAU> <FILE_ID_LAU> ltorres@arval.com.mx` e importarlo con la sesión de Lau como **Create as new**, eligiendo o creando sus conexiones de Outlook, Excel y OneDrive.
4. Volver a elegir `Duplicados - revisar` en Mover_a_duplicados, poner `varCorreoOperadora = ltorres@arval.com.mx`, guardar y encender.
5. Quitar la regla de redirección a soluciones@.
6. En las rutinas: `M365_USUARIO=ltorres@arval.com.mx` y la política de acceso de la aplicación de Graph (Exchange) ampliada al buzón de Lau; `ONEDRIVE_WEB_BASE` apuntando a su OneDrive. Volver a correr `python cli.py selftest`.
7. Una semana con `varPermitirMover = false`; después `true` si Lau quiere que los duplicados exactos vayan a su papelera.

### Verificación (cualquiera de las dos)

Repetir los casos 1, 2 y 4 de la Fase 4 del plan original: XML + PDF de un cliente conocido, duplicado exacto, y correo con foto. Los archivos deben caer en la carpeta correcta y las filas en el Excel; después la rutina debe reflejarlo en el panel en su siguiente corrida.
