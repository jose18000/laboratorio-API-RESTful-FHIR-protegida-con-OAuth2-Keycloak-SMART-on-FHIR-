#!/usr/bin/env bash
# Pruebas del laboratorio: 201 con token, 401 sin token / token falso, 403 solo-lectura.
# Uso: export KC_PASSWORD='tu-clave'; bash scripts/pruebas.sh
set -u
REALM=${KC_REALM:-fhir-lab}; CLIENT=${KC_CLIENT_ID:-smart-lab-client}; USER_=${KC_USER:-dr.reyes}
: "${KC_PASSWORD:?Define KC_PASSWORD}"
BASE=http://localhost:8000/fhir
BODY='{"resourceType":"Patient","name":[{"use":"official","family":"Reyes","given":["Jaider"]}]}'

get_token() {  # $1 = scope
  curl -s -X POST "http://localhost:8081/realms/$REALM/protocol/openid-connect/token" \
    -d grant_type=password -d client_id="$CLIENT" -d username="$USER_" \
    -d "password=$KC_PASSWORD" -d "scope=$1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

TW=$(get_token 'openid patient/*.write patient/*.read')
TR=$(get_token 'openid patient/*.read')
H='Content-Type: application/fhir+json'

echo "GET  /metadata (publico)  esperado 200 -> $(code $BASE/metadata)"
echo "POST token .write         esperado 201 -> $(code -X POST $BASE/Patient -H "Authorization: Bearer $TW" -H "$H" -d "$BODY")"
echo "POST sin token            esperado 401 -> $(code -X POST $BASE/Patient -H "$H" -d "$BODY")"
echo "POST token falso          esperado 401 -> $(code -X POST $BASE/Patient -H 'Authorization: Bearer token.falso.123' -H "$H" -d "$BODY")"
echo "POST token solo .read     esperado 403 -> $(code -X POST $BASE/Patient -H "Authorization: Bearer $TR" -H "$H" -d "$BODY")"
echo "GET  token solo .read     esperado 200 -> $(code $BASE/Patient -H "Authorization: Bearer $TR")"
