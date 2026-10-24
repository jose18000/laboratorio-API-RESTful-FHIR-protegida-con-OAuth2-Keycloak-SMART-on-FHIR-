"""Obtiene un token de Keycloak y hace POST /Patient al gateway.

Uso:
    export KC_PASSWORD='tu-clave'
    python scripts/post_patient.py
"""
import json
import os
import sys

import requests

REALM     = os.getenv("KC_REALM", "fhir-lab")
CLIENT_ID = os.getenv("KC_CLIENT_ID", "smart-lab-client")
USER      = os.getenv("KC_USER", "dr.reyes")
PASSWORD  = os.getenv("KC_PASSWORD")
KEYCLOAK  = f"http://localhost:8081/realms/{REALM}/protocol/openid-connect/token"
FHIR      = os.getenv("FHIR_BASE", "http://localhost:8000/fhir")

if not PASSWORD:
    sys.exit("Define la variable de entorno KC_PASSWORD")

# 1) Token (password grant: SOLO laboratorio)
r = requests.post(KEYCLOAK, data={
    "grant_type": "password", "client_id": CLIENT_ID,
    "username": USER, "password": PASSWORD,
    "scope": "openid patient/*.write patient/*.read",
})
r.raise_for_status()
token = r.json()["access_token"]
print("Token obtenido, scope:", r.json()["scope"])

# 2) POST /Patient
patient = {"resourceType": "Patient",
           "name": [{"use": "official", "family": "Reyes", "given": ["Jaider"]}]}
resp = requests.post(f"{FHIR}/Patient", data=json.dumps(patient),
                     headers={"Authorization": f"Bearer {token}",
                              "Content-Type": "application/fhir+json"})
print("HTTP", resp.status_code)
print("Location:", resp.headers.get("Location"))
print(json.dumps(resp.json(), indent=2))
