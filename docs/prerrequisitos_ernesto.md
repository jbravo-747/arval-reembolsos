# Prerrequisitos para ejecutar el Plan v2 (lista para el administrador del tenant)

Solicitante: Joel Bravo. Proyecto: organizador de reembolsos del buzón de Lau. Fecha: 8 de octubre de 2026.

## 1. Claude para empresas

- Contratar el plan y asignar asientos a Joel (implementación) y a Lau (uso del panel).
- Habilitar en la organización: Claude Code con rutinas en la nube (agentes programados), artifacts y el conector Microsoft 365.
- Confirmar con Anthropic, en el contrato, el tratamiento de información de salud: retención cero de datos y acuerdo de confidencialidad aplicable. Hasta tenerlo, Claude solo procesa metadatos.

## 2. Registro de aplicación en Microsoft Entra ID (para que la rutina escriba en OneDrive, Excel y correo)

1. Entra ID > Registros de aplicaciones > Nuevo registro: nombre `Reembolsos-Claude`, cuenta de este directorio únicamente.
2. Certificados y secretos > Nuevo secreto de cliente (vigencia 12 meses; anotar fecha de renovación).
3. Permisos de API > Microsoft Graph > Permisos de aplicación:
   - `Files.ReadWrite.All` (o, si prefieren acotar, `Sites.Selected` concedido solo al OneDrive de soluciones@).
   - `Mail.Send`.
   - Conceder consentimiento de administrador.
4. Limitar el alcance del correo con una política de acceso a aplicaciones de Exchange Online para que la aplicación solo pueda actuar sobre el buzón de soluciones@arval.com.mx:
   `New-ApplicationAccessPolicy -AppId <client id> -PolicyScopeGroupId soluciones@arval.com.mx -AccessRight RestrictAccess`
5. Entregar a Joel por un canal seguro: Tenant ID, Client ID y el secreto. Nunca por correo ni en el repositorio.

## 3. Repositorio

- Crear el repositorio privado `arval-reembolsos` en la organización de GitHub de Arval (o autorizar el de Joel) y conectarlo a Claude Code en la cuenta de empresa.

## 4. Verificación de salida (lo hace Joel con Claude)

- `python cli.py selftest` desde una rutina de prueba: autentica, lista `/Reembolsos` y lee la tabla `tblRegistro`.
- Un movimiento de archivo de prueba y una fila de prueba en `tblMonitor` en modo `aplica`.

## Costos

- Plan de Claude para empresas: según contrato (asientos de Joel y Lau).
- Entra ID y Microsoft Graph: incluidos en Microsoft 365.
- Power Automate Premium / AI Builder: ya no se necesitan.
