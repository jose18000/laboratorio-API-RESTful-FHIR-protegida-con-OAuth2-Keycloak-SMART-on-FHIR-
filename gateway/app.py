import json
import os

import httpx
import jwt
from fastapi import FastAPI, Request, Response
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

HAPI_URL    = os.getenv("HAPI_URL", "http://hapi:8080")
ISSUER      = os.getenv("ISSUER", "http://localhost:8081/realms/fhir-lab")
JWKS_URL    = os.getenv("JWKS_URL", "http://keycloak:8080/realms/fhir-lab/protocol/openid-connect/certs")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "http://localhost:8000")

jwks_client = PyJWKClient(JWKS_URL, cache_keys=True)  # cachea las claves publicas
http = httpx.AsyncClient(timeout=30)
app = FastAPI(title="FHIR Gateway (PEP)")


def outcome(status, code, msg, extra_headers=None):
    """Devuelve un OperationOutcome FHIR con el error."""
    body = {"resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": code, "diagnostics": msg}]}
    return Response(json.dumps(body), status_code=status,
                    media_type="application/fhir+json", headers=extra_headers)


def scope_allows(scopes, method, resource):
    """SMART v1: contexto/Recurso.permiso  (patient|user|system)/(*|Tipo).(read|write|*)"""
    need = "read" if method in ("GET", "HEAD") else "write"
    for s in scopes:
        if "/" not in s or "." not in s:
            continue
        ctx, rest = s.split("/", 1)
        if ctx not in ("patient", "user", "system"):
            continue
        res, perm = rest.rsplit(".", 1)
        if res in ("*", resource) and perm in (need, "*"):
            return True
    return False


@app.api_route("/fhir/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    # 1) /metadata es publico por convencion FHIR/SMART (CapabilityStatement)
    if not (request.method == "GET" and path.rstrip("/") == "metadata"):
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return outcome(401, "login", "Falta el token Bearer",
                           {"WWW-Authenticate": 'Bearer realm="fhir-lab"'})
        token = auth[7:].strip()

        # 2) Validar firma, issuer y expiracion
        try:
            key = jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER,
                                options={"verify_aud": False, "require": ["exp", "iss"]})
        except jwt.ExpiredSignatureError:
            return outcome(401, "login", "Token expirado",
                           {"WWW-Authenticate": 'Bearer error="invalid_token", error_description="expired"'})
        except PyJWKClientConnectionError:
            return outcome(503, "transient", "No se pudo contactar a Keycloak (JWKS)")
        except jwt.PyJWTError as e:
            return outcome(401, "login", f"Token invalido: {e}",
                           {"WWW-Authenticate": 'Bearer error="invalid_token"'})

        # 3) Validar scope SMART
        scopes = claims.get("scope", "").split()
        resource = path.split("/")[0]
        if not scope_allows(scopes, request.method, resource):
            return outcome(403, "forbidden",
                           f"Scope insuficiente para {request.method} /{resource}",
                           {"WWW-Authenticate": 'Bearer error="insufficient_scope"'})

    # 4) Reenviar a HAPI (sin el header Authorization)
    fwd = {k: v for k, v in request.headers.items()
           if k.lower() in ("content-type", "accept", "prefer", "if-match", "if-none-exist")}
    r = await http.request(request.method, f"{HAPI_URL}/fhir/{path}",
                           params=request.query_params, content=await request.body(), headers=fwd)

    out = {}
    for h in ("content-type", "etag", "last-modified", "location", "content-location"):
        if h in r.headers:
            out[h] = r.headers[h].replace(f"{HAPI_URL}/fhir", f"{PUBLIC_BASE}/fhir")
    return Response(r.content, status_code=r.status_code, headers=out)
