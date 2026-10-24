# API RESTful FHIR protegida con OAuth2 (HAPI FHIR + Keycloak + SMART on FHIR)

**Autores:** Jose Guillermo Canchila Essis y Santiago Fuentes· Ingeniería de Sistemas, 9.º semestre
**Asignatura:** Sistemas distribuidos · **Docente:** Jaider Reyes Herazo · **Fecha:** octubre 2026

Laboratorio práctico de interoperabilidad en salud y seguridad de APIs. Se despliega un servidor **HAPI FHIR (R4)** y se protege con **OAuth2 / OpenID Connect** usando **Keycloak** y un **gateway** (FastAPI) que valida el JWT y los *scopes* de estilo **SMART on FHIR** antes de reenviar la petición.

> ⚠️ **Proyecto educativo.** Usa credenciales triviales, HTTP sin TLS y *password grant*. **No lo uses en producción ni con datos reales de pacientes.**

## Qué demuestra

| Prueba | Resultado esperado |
|---|---|
| `POST /Patient` con token válido y `patient/*.write` | `201 Created` |
| `POST /Patient` sin token | `401 Unauthorized` |
| `POST /Patient` con token falso | `401 Unauthorized` |
| `POST /Patient` con token solo `patient/*.read` | `403 Forbidden` |
| `GET /Patient` con token `patient/*.read` | `200 OK` |
| Acceso directo a HAPI (`:8080`) con el puerto cerrado | Conexión rechazada |

## Arquitectura

```
Cliente (curl / Python / Postman)
   |  :8081 (token)              |  :8000 /fhir/*
   v                             v
Keycloak  <---- JWKS ----  Gateway (PEP)  ---->  HAPI FHIR
 (IdP)                     valida firma, iss,     (solo red interna,
                           exp y scope SMART       sin puerto publicado)
                    red Docker: fhirnet
```

| Servicio | Puerto host | Función |
|---|---|---|
| Keycloak 26 | `8081` | Servidor de autorización (emite JWT) |
| Gateway FastAPI | `8000` | Punto de aplicación de políticas (PEP) |
| HAPI FHIR | — (interno) | Servidor FHIR R4 |

## Requisitos

- Docker y Docker Compose v2
- Python 3.10+ (solo para los scripts)
- 4 GB de RAM libres (recomendado 6–8 GB) y los puertos `8000` y `8081` libres (`8080` solo si habilitas la línea base insegura)

## Inicio rápido

```bash
git clone https://github.com/jose18000/laboratorio-API-RESTful-FHIR-protegida-con-OAuth2-Keycloak-SMART-on-FHIR-.git
docker compose up -d --build
docker compose logs -f keycloak     # espera "started in ..." y sal con Ctrl+C
```

HAPI tarda 30–90 s en arrancar. Verifica:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/fhir/metadata   # 200
```

## Configuración de Keycloak (manual)

Abre `http://localhost:8081/` → *Administration Console* (`admin` / `admin`).

1. **Realm:** crea `fhir-lab`.
2. **Client scopes:** crea `patient/*.write` y `patient/*.read` (Type: `None`, Protocol: OpenID Connect, *Include in token scope*: ON).
3. **Client:** `smart-lab-client`
   - Client authentication: **OFF** (cliente público)
   - Standard flow: **ON**; Direct access grants: **ON**
   - Valid redirect URIs: `https://oauth.pstmn.io/v1/callback`; Web origins: `+`
   - *Advanced* → PKCE Code Challenge Method: `S256`
   - *Client scopes* → añade ambos scopes como **Optional**
4. **Usuario:** `dr.reyes` con email, nombre y apellido; *Email verified* ON; en *Credentials* fija una contraseña con **Temporary = OFF**.

> Si tu versión rechaza `*` o `/` en el nombre del scope, usa `patient.write` / `patient.read` y ajusta `scope_allows` en `gateway/app.py`.

## Uso

Define tus credenciales (no se guardan en el repositorio):

```bash
cp .env.example .env              # opcional, referencia
export KC_PASSWORD='la-clave-que-pusiste-en-keycloak'
```

### Obtener un token

```bash
TOKEN=$(curl -s -X POST http://localhost:8081/realms/fhir-lab/protocol/openid-connect/token \
  -d grant_type=password -d client_id=smart-lab-client \
  -d username=dr.reyes -d "password=$KC_PASSWORD" \
  -d 'scope=openid patient/*.write patient/*.read' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

El token dura 300 s; repite el comando cuando caduque.

### POST /Patient con token

```bash
curl -i -X POST http://localhost:8000/fhir/Patient \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/fhir+json" \
  -d '{"resourceType":"Patient","name":[{"use":"official","family":"Reyes","given":["Jaider"]}]}'
```

### POST /Patient sin token (rechazado)

```bash
curl -i -X POST http://localhost:8000/fhir/Patient \
  -H "Content-Type: application/fhir+json" \
  -d '{"resourceType":"Patient","name":[{"family":"Reyes"}]}'
# HTTP/1.1 401 Unauthorized
```

### Con Python o en lote

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/post_patient.py          # token + POST /Patient
bash scripts/pruebas.sh                 # batería completa 201/401/403
```

### Con Postman

`POST http://localhost:8000/fhir/Patient` → pestaña *Authorization* → OAuth 2.0 → *Authorization Code (With PKCE)*:

| Campo | Valor |
|---|---|
| Callback URL | `https://oauth.pstmn.io/v1/callback` (Authorize using browser) |
| Auth URL | `http://localhost:8081/realms/fhir-lab/protocol/openid-connect/auth` |
| Access Token URL | `http://localhost:8081/realms/fhir-lab/protocol/openid-connect/token` |
| Client ID | `smart-lab-client` |
| Code Challenge Method | SHA-256 |
| Scope | `openid patient/*.write patient/*.read` |

## Línea base insegura (opcional)

Para reproducir el "antes", descomenta `ports: - "8080:8080"` en el servicio `hapi` de `docker-compose.yml` y ejecuta `docker compose up -d`. Un `POST` a `http://localhost:8080/fhir/Patient` devolverá `201` sin token. Vuelve a comentarlo para cerrar la puerta trasera. Los datos de HAPI (H2) se pierden al recrear el contenedor.

## Cómo funciona el gateway

`gateway/app.py` aplica, en orden:

1. Exige `Authorization: Bearer <jwt>` (si no, **401**). `GET /metadata` es público.
2. Verifica la firma RS256 con el JWKS de Keycloak, además de `iss` y `exp` (si falla, **401**).
3. Verifica el scope SMART: `GET` requiere `*.read`; `POST/PUT/PATCH/DELETE` requieren `*.write` (si no, **403**).
4. Reenvía a HAPI por la red interna.

## Estructura del repositorio

```
.
├── docker-compose.yml        # HAPI + Keycloak + gateway
├── gateway/
│   ├── app.py                # PEP: valida JWT y scopes SMART
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── post_patient.py       # token + POST /Patient (requests)
│   ├── pruebas.sh            # pruebas 201 / 401 / 403
│   └── requirements.txt
├── docs/evidencias/          # capturas de pantalla del laboratorio
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Account is not fully set up` | Usuario sin email/nombre/apellido | Completa los datos en Keycloak |
| `invalid_scope` | Scope no asignado al client | Añádelo como *Optional* |
| `401 Invalid issuer` | `ISSUER` ≠ `iss` del token | Debe ser `http://localhost:8081/realms/fhir-lab` |
| `401 Token expirado` | Pasaron más de 300 s | Pide un token nuevo |
| `403 Scope insuficiente` | El token no incluye `.write` | Pide el token con `scope=` correcto |
| `500`/`502` en el gateway | HAPI aún arrancando | Espera 30–90 s |
| `503` JWKS | Keycloak no está listo | `docker compose logs keycloak` |

## Limitaciones conocidas

- Keycloak no implementa de forma nativa el contexto de lanzamiento SMART (`launch/patient`, `fhirUser`); los scopes se emulan como *client scopes*.
- *Password grant* está desaconsejado en OAuth 2.1; el flujo recomendado es Authorization Code + PKCE.
- No se valida `aud`; el tráfico va por HTTP sin TLS; las credenciales de administración son triviales.
- El gateway no captura `ConnectError` (responde 500 si HAPI está caído) y deja visibles nombres internos (`hapi:8080`) en el cuerpo de las respuestas.
- Sin auditoría ni restricción por paciente.

## Referencias

- [HL7 FHIR R4](https://hl7.org/fhir/R4/) · [SMART App Launch](https://hl7.org/fhir/smart-app-launch/)
- [RFC 6749 (OAuth 2.0)](https://www.rfc-editor.org/rfc/rfc6749) · [RFC 6750 (Bearer Token)](https://www.rfc-editor.org/rfc/rfc6750)
- [Keycloak](https://www.keycloak.org/documentation) · [HAPI FHIR](https://hapifhir.io/)

## Licencia

MIT. Consulta [LICENSE](LICENSE).
