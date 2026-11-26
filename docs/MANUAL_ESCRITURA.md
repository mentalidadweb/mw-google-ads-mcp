# Manual: escritura restringida por lista de correos

Este modo deja que **solo algunas personas** usen las herramientas de escritura del servidor MCP de Google Ads. El resto del equipo sigue en solo lectura con el mismo conector. La lista de personas se define con una variable de entorno en Railway.

No agrega herramientas nuevas: habilita las que ya trae el servidor de Google y las limita a la lista.

## Ruta rápida

1. Despliega la rama `mw/escritura-whitelist` en Railway.
2. Cambia `GOOGLE_ADS_MCP_TOOLS_CONFIG` a `/app/tools_config_escritura.yaml`.
3. Agrega `GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS` con los correos autorizados, separados por comas.
4. Vuelve a desplegar.
5. Las personas autorizadas desconectan y vuelven a conectar el conector en Claude para ver las herramientas nuevas.
6. Haz las pruebas de aceptación del final de este manual.

## Qué pueden hacer las personas autorizadas

| Herramienta | Qué hace en Google Ads |
| --- | --- |
| `labels_manage_labels` | Crea, edita o elimina etiquetas de la cuenta. |
| `labels_manage_label_associations` | Asigna o quita etiquetas en campañas, en la cuenta, en grupos de anuncios o en criterios (por ejemplo, keywords). |
| `assets_create_asset` | Crea assets nuevos: texto, imagen, video de YouTube, sitelink, callout, structured snippet y otros. No edita ni borra assets existentes. |

**No se puede** pausar ni activar campañas, cambiar presupuestos, pujas o estrategias, ni crear o editar anuncios y keywords. El servidor no tiene herramientas para eso.

`upload_video_asset` queda **siempre desactivada**. Esa herramienta sube a YouTube un archivo del disco del servidor, y en Railway podría usarse para leer archivos internos. Además corre como tarea en segundo plano, y las consultas posteriores sobre una tarea (`tasks/get`, `tasks/cancel`) no pasan por la lista. No la agregues a `tools_config_escritura.yaml`.

## Variables de entorno

| Variable | Valor | Notas |
| --- | --- | --- |
| `GOOGLE_ADS_MCP_TOOLS_CONFIG` | `/app/tools_config_escritura.yaml` | Para volver a solo lectura, usa `/app/tools_config.yaml`. |
| `GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS` | `ana@mentalidadweb.com,juan@mentalidadweb.com` | Correos completos, separados por comas. No distingue mayúsculas. Los espacios se ignoran. |
| `GOOGLE_ADS_MCP_ALLOWED_DOMAINS` | `mentalidadweb.com` | **Obligatoria en este modo.** La lista de escritura compara el correo exacto, pero es esta variable la que exige una cuenta de Google Workspace del dominio. Sin ella, una cuenta personal de Google registrada con un correo de la lista podría pasar. |

Las demás variables no cambian (ver [DESPLIEGUE_RAILWAY.md](DESPLIEGUE_RAILWAY.md)).

> Si `GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS` está vacía o no existe, **nadie** ve las herramientas de escritura. Es el comportamiento seguro por defecto.

Las entradas mal escritas (por ejemplo, `mentalidadweb.com` sin usuario) se ignoran y quedan registradas como advertencia en los logs. Al arrancar, el log muestra cuántos correos se cargaron: `Write tools allowlist loaded with N email(s).`

## Cómo funciona

1. Cada persona inicia sesión con su cuenta de Google, como en el modo solo lectura.
2. En cada solicitud, el servidor lee el correo **verificado** de esa cuenta.
3. Si la herramienta está marcada como de solo lectura (`readOnlyHint=True`), cualquier persona autenticada puede usarla.
4. Si no lo está, solo puede usarla un correo de la lista. Esto incluye cualquier herramienta futura que llegue de Google sin esa marca.
5. A quien no está en la lista, las herramientas de escritura **no le aparecen**, y si intenta llamarlas igual, la llamada se rechaza con `Authorization failed`.

Además hay dos protecciones que ya traía el servidor:

- **Rol en Google Ads.** Estar en la lista no da permisos nuevos en Google Ads. La persona solo puede escribir en las cuentas donde su usuario tiene acceso de tipo Estándar o Administrador. Con acceso de solo lectura en Google Ads, la API rechaza el cambio.
- **Confirmación en dos pasos.** Cada herramienta de escritura primero valida el cambio sin aplicarlo (`validate_only=True`) y devuelve un `checksum`. El cambio solo se aplica en una segunda llamada con ese mismo `checksum`. Si cambia cualquier dato, el cambio se rechaza.

En la práctica, Claude primero muestra lo que va a hacer y pide confirmación antes de aplicarlo.

## Agregar o quitar personas

1. En Railway, edita `GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS`.
2. Aplica los cambios y vuelve a desplegar. Hay unos segundos sin servicio, porque el servicio usa un volumen.
3. Revisa en el log la cantidad de correos cargados.
4. Quien fue agregado debe desconectar y volver a conectar el conector en Claude para que aparezcan las herramientas.

Las sesiones no se pierden con el nuevo despliegue, porque los tokens están en el volumen `/data`.

## Volver a solo lectura

Cambia `GOOGLE_ADS_MCP_TOOLS_CONFIG` a `/app/tools_config.yaml` y vuelve a desplegar. Con esa configuración las herramientas de escritura ni siquiera se registran, aunque la lista tenga correos.

## Auditoría

Cada llamada a una herramienta queda en el registro de auditoría (`/data/audit`, cifrado), con su resultado. El registro distingue la validación (propuesta) de la confirmación del cambio.

## Pruebas de aceptación

- [ ] El log muestra `Write tools allowlist loaded with N email(s).` con el número esperado.
- [ ] Una persona **de la lista** ve, además de las 3 de lectura, `manage_labels`, `manage_label_associations` y `create_asset`.
- [ ] Una persona **fuera de la lista** ve solo `list_accessible_customers`, `search` y `get_resource_metadata`.
- [ ] Una persona de la lista pide "crea la etiqueta Prueba MCP en la cuenta X": Claude valida, muestra el cambio y lo aplica solo después de confirmar. Luego se elimina la etiqueta.
- [ ] Una persona fuera de la lista pide lo mismo: Claude responde que no tiene herramientas para hacerlo.
- [ ] Nadie ve `upload_video_asset`.

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| Una persona de la lista no ve las herramientas de escritura | Claude guardó la lista de herramientas de antes. | Desconectar y volver a conectar el conector. |
| Nadie ve las herramientas de escritura | Falta `GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS`, el correo está mal escrito o `GOOGLE_ADS_MCP_TOOLS_CONFIG` sigue en `/app/tools_config.yaml`. | Revisar las variables y el log de arranque. |
| `Authorization failed for tool ...` | La persona no está en la lista o su correo no está verificado. | Agregar el correo exacto con el que inicia sesión. |
| `USER_PERMISSION_DENIED` o `AUTHORIZATION_ERROR` de Google Ads al aplicar un cambio | La persona tiene acceso de solo lectura en esa cuenta de Google Ads o falta indicar la MCC. | Dar acceso Estándar en Google Ads o indicar la MCC (`login_customer_id`) en la consulta. |

## Para desarrolladores

| Archivo | Rol |
| --- | --- |
| `ads_mcp/mw_escritura.py` | Lectura de la lista (`get_write_allowed_emails`), regla de acceso (`WriteAccessCheck`) e instalación del middleware (`install_write_access_middleware`). |
| `ads_mcp/mw_seguridad.py` | `get_verified_email`, compartida con la restricción de dominio. |
| `ads_mcp/coordinator.py` | Gancho de una línea que instala el middleware. |
| `tools_config_escritura.yaml` | Habilita `labels` y solo `create_asset` dentro de `assets`. |
| `tests/mw_escritura_test.py` | Tests unitarios y de integración del modo escritura. |

La regla usa `AuthMiddleware` de FastMCP (`fastmcp.server.middleware`), que filtra `tools/list` y bloquea `tools/call` por persona. Solo se instala en modo OAuth remoto. En modo local (stdio) no hay identidad OAuth y FastMCP no aplica estas reglas.

Para correr los tests:

```shell
.venv/bin/python -m unittest tests.mw_escritura_test tests.mw_seguridad_test
```
