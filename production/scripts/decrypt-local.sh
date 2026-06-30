#!/bin/sh
# Decrypt production/.env.render to production/.env.render.dec for local script use.
# Requires: sops on PATH (or SOPS_BIN set), age private key at the default
# sops lookup path (Windows: %APPDATA%\sops\age\keys.txt).
set -e

SOPS="${SOPS_BIN:-sops}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

"$SOPS" -d --input-type dotenv --output-type dotenv \
    "$REPO_ROOT/production/.env.render" > "$REPO_ROOT/production/.env.render.dec"

echo "Decrypted to production/.env.render.dec"
