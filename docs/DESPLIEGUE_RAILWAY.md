# Despliegue en Railway (solo lectura)

Esta guía deja el servidor MCP de Google Ads en Railway para que el equipo de Mentalidad Web consulte Google Ads desde Claude **en modo solo lectura**. Cada persona entra con su propia cuenta de mentalidadweb.com y ve solo las cuentas a las que ya tiene acceso en Google Ads. El servidor no usa credenciales propias ni developer token.

## Ruta rápida

1. Google Cloud: pantalla de consentimiento Interna, scope `adwords` y cliente OAuth web con dos URIs de redirección.
2. Railway: servicio desde el repo, dominio, volumen en `/data`, variables, una réplica y nuevo despliegue.
3. Claude: conector personalizado con `https://DOMINIO/mcp` y el cliente OAuth de Claude (CIMD).
4. Cada persona: passkey, acceso de lectura en Google Ads con su correo de mentalidadweb.com y primera prueba.
5. Pruebas de aceptación.

## Qué protege esta configuración

| Riesgo | Protección |
| --- | --- |
| Cambios en cuentas de Google Ads | `tools_config.yaml` solo habilita `customers`, `search` y `metadata`. No se registran `manage_labels`, `manage_label_associations`, `create_asset` ni `upload_video`. |
| Uso de credenciales del servidor | En modo remoto, si una solicitud no trae token de usuario, el servidor responde con error y nunca usa Application Default Credentials. |
| Personas fuera de la empresa | `GOOGLE_ADS_MCP_ALLOWED_DOMAINS` rechaza con HTTP 401 a cualquier cuenta que no sea de Google Workspace del dominio permitido. Además, la pantalla de consentimiento Interna solo admite usuarios de la organización. |
| Ver cuentas ajenas | Google Ads aplica los accesos de cada persona. El servidor no tiene tablas de permisos propias. |

## a. Google Cloud

Trabaja en el proyecto de Google Cloud que tiene aprobado el acceso Basic a la Google Ads API. Un cliente OAuth de otro proyecto produce `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`.

1. Confirma que la **Google Ads API** está habilitada en el proyecto.
2. En **Google Auth Platform > Branding / Audiencia**, configura la pantalla de consentimiento con tipo de usuario **Interna**.
3. En **Acceso a datos**, agrega los scopes:
   - `https://www.googleapis.com/auth/adwords`
   - `openid`, `https://www.googleapis.com/auth/userinfo.email` y `https://www.googleapis.com/auth/userinfo.profile` (el servidor los exige para identificar a la persona).
4. En **Clientes**, crea un cliente OAuth de tipo **Web application**.
5. En **URIs de redireccionamiento autorizados**, registra:

   | URI | Para qué sirve |
   | --- | --- |
   | `https://DOMINIO/auth/callback` | Retorno de Google al servidor (proxy OAuth). Es `GOOGLE_ADS_MCP_BASE_URL` más `/auth/callback`. Es la única URI que Google usa. |
   | `https://claude.ai/api/mcp/auth_callback` | Opcional. Es el retorno de Claude, pero Claude vuelve desde nuestro servidor, no desde Google. Tenerla registrada no causa problemas. |

   La ruta `/auth/callback` es el valor por defecto de `redirect_path` en el `GoogleProvider` de FastMCP (`OAuthProxy` usa `"/auth/callback"` cuando no se indica otra) y este servidor no la cambia. Usa el dominio final (por ejemplo `https://ads-mcp.mentalidadweb.com`), sin barra al final y con `https`.

6. Guarda el **client id** y el **client secret**. Solo se cargan en Railway: Claude no los usa.

> Si todavía no tienes el dominio de Railway, crea primero el servicio (paso b.2), copia el dominio y vuelve a este punto.

## b. Railway

1. Crea un servicio desde este repositorio (rama de despliegue acordada). Railway lee `railway.toml` y construye con el `Dockerfile`.
2. En **Settings > Networking**, genera un dominio público. Anota `https://DOMINIO`.
3. Agrega un **volumen** al servicio montado en `/data`. Ahí quedan los tokens OAuth (`/data/oauth`) y la auditoría (`/data/audit`), ambos cifrados.
4. Genera las claves en tu equipo y cópialas directo en Railway, sin guardarlas en archivos:

   ```shell
   python scripts/generar_claves.py
   ```

5. Carga las variables en **Variables**. La plantilla con comentarios está en `.env.railway.example`.

   | Variable | Valor |
   | --- | --- |
   | `GOOGLE_ADS_MCP_OAUTH_CLIENT_ID` | client id del paso a.6 |
   | `GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET` | client secret del paso a.6 |
   | `GOOGLE_ADS_MCP_BASE_URL` | `https://DOMINIO` |
   | `GOOGLE_ADS_MCP_JWT_SIGNING_KEY` | salida de `generar_claves.py` |
   | `GOOGLE_ADS_MCP_TOOLS_CONFIG` | `/app/tools_config.yaml` |
   | `GOOGLE_ADS_MCP_ALLOWED_DOMAINS` | `mentalidadweb.com` |
   | `GOOGLE_ADS_MCP_STORAGE_TYPE` | `filetree` |
   | `GOOGLE_ADS_MCP_STORAGE_PATH` | `/data/oauth` |
   | `GOOGLE_ADS_MCP_STORAGE_ENCRYPTION_KEY` | salida de `generar_claves.py` |
   | `GOOGLE_ADS_MCP_AUDIT_STORAGE_TYPE` | `filetree` |
   | `GOOGLE_ADS_MCP_AUDIT_STORAGE_PATH` | `/data/audit` |
   | `GOOGLE_ADS_MCP_AUDIT_STORAGE_ENCRYPTION_KEY` | salida de `generar_claves.py` |

   **No definas** `GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `GOOGLE_APPLICATION_CREDENTIALS` ni `GOOGLE_ADS_DEVELOPER_TOKEN` (la plantilla explica por qué). Tampoco definas `PORT`: Railway la asigna y el servidor escucha en `0.0.0.0` en ese puerto.

6. Deja el servicio con **una sola réplica** (`railway.toml` ya fija `numReplicas = 1`; Railway no permite réplicas con volumen).
7. Vuelve a desplegar después de definir `GOOGLE_ADS_MCP_BASE_URL`. Sin ese valor el servidor anuncia `http://localhost:8080` y el login falla.
8. Revisa los logs: debe aparecer `Uvicorn running on http://0.0.0.0:<PORT>`.
9. Comprueba desde tu equipo que el servidor pide autenticación:

   ```shell
   curl -i -X POST https://DOMINIO/mcp \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"prueba","version":"1"}}}'
   ```

   Resultado esperado: `HTTP/1.1 401 Unauthorized`.

No hay healthcheck configurado: el servidor no expone una ruta de salud y `/mcp` responde 401 sin autenticación.

## c. Claude

1. Como administrador de la organización, ve a **Configuración de la organización > Conectores > Agregar > Conector personalizado**.
2. **URL del servidor:** `https://DOMINIO/mcp`. **Nombre:** por ejemplo `Google Ads Mentalidad Web`.
3. **Método de inicio de sesión:** OAuth (Claude lo detecta solo).
4. **Cliente OAuth:** deja **Cliente OAuth de Claude (CIMD)**. No ingreses el client id ni el secret de Google: Claude se registra ante nuestro servidor, y el servidor es el único que habla con Google. El servidor no acepta autenticación de clientes con secret.
5. Pulsa **Agregar**. Cada persona se conecta después con su propia cuenta.

## d. Onboarding de cada persona

1. **Passkey con anticipación.** Crea una passkey en [g.co/passkeys](https://g.co/passkeys) con la cuenta de mentalidadweb.com. Puede tardar hasta 7 días en quedar habilitada, así que hazlo antes de la fecha de conexión.
2. **Acceso en Google Ads.** La persona necesita acceso de solo lectura a sus cuentas, o a su sub MCC, con **el mismo correo de mentalidadweb.com** con el que entrará a Claude. Un acceso dado a otro correo no sirve.
3. **Conexión.** En Claude, abre el conector y pulsa **Conectar**. Inicia sesión con la cuenta de mentalidadweb.com y acepta los permisos.
4. **Primera prueba.** Pregunta: "¿a qué cuentas tengo acceso?". Debe listar solo las cuentas de esa persona.
5. Si las cuentas están bajo una MCC, indica la MCC en la consulta (por ejemplo, "usa la MCC 123-456-7890"). La herramienta de búsqueda acepta `login_customer_id` por consulta.

## e. Pruebas de aceptación

- [ ] **Cada persona ve solo lo suyo.** Dos personas con accesos distintos preguntan "¿a qué cuentas tengo acceso?" y obtienen listas distintas, que coinciden con lo que ven en la interfaz de Google Ads.
- [ ] **Sin escritura.** Pedir "pausa la campaña X" responde que no hay herramientas para hacerlo. El conector solo muestra `list_accessible_customers`, `search` y `get_resource_metadata`.
- [ ] **Dominio restringido.** Un correo fuera de mentalidadweb.com (por ejemplo, una cuenta gmail.com) no logra usar el conector: la pantalla Interna lo bloquea o el servidor responde 401.
- [ ] **Sin credenciales del servidor.** No existen `GOOGLE_APPLICATION_CREDENTIALS` ni `GOOGLE_ADS_DEVELOPER_TOKEN` en las variables de Railway.
- [ ] **Persistencia.** Después de un nuevo despliegue, las personas siguen conectadas sin volver a iniciar sesión.

## f. Problemas frecuentes

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| `redirect_uri_mismatch` al iniciar sesión | Falta la URI de redirección del servidor o no coincide exactamente (http en vez de https, barra final, dominio antiguo). | Registra `https://DOMINIO/auth/callback` en el cliente OAuth de Google. Revisa que `GOOGLE_ADS_MCP_BASE_URL` sea igual a `https://DOMINIO`. |
| `USER_PERMISSION_DENIED` | La cuenta se administra a través de una MCC y la consulta no indica `login_customer_id`, o se indicó una MCC a la que la persona no tiene acceso. | Indica en la consulta la MCC correcta de esa persona. No definas `GOOGLE_ADS_LOGIN_CUSTOMER_ID` en Railway. |
| `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` | El cliente OAuth pertenece a un proyecto de Google Cloud sin acceso Basic aprobado. | Crea el cliente OAuth en el proyecto con acceso Basic y actualiza client id y secret en Railway. |
| Todos deben reconectarse tras cada reinicio | No hay volumen en `/data` o las variables de almacenamiento apuntan a otra ruta. | Monta el volumen en `/data` y revisa `GOOGLE_ADS_MCP_STORAGE_PATH=/data/oauth`. No cambies las claves de cifrado ni la de JWT: al cambiarlas se invalidan las sesiones guardadas. |
| 401 permanente para una persona de la empresa | La cuenta no es de Google Workspace de mentalidadweb.com o su correo no está verificado. | Confirma que entra con la cuenta corporativa y no con una cuenta personal. |
| "No hay un token de usuario para esta solicitud" | La sesión expiró o se perdió. | Desconecta y vuelve a conectar el conector en Claude. |

## Referencia técnica

- Restricción de dominio: `ads_mcp/mw_seguridad.py`, clase `DomainRestrictedGoogleProvider`. Exige `email_verified`, que el dominio del correo esté en la lista y que el dominio de Workspace (`hd`, entregado por el endpoint userinfo de Google) también lo esté. Se aplica en `verify_token`, el método que el backend de autenticación llama en cada solicitud HTTP.
- Bloqueo de credenciales del servidor: `forbid_server_credentials_in_remote_mode`, llamado desde `ads_mcp/utils.py` antes del respaldo con Application Default Credentials.
- Tests: `tests/mw_seguridad_test.py`.
