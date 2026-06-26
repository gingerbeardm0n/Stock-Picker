#!/bin/sh
set -e

# Decrypt SOPS-encrypted env file if SOPS_AGE_KEY is set
if [ -n "$SOPS_AGE_KEY" ] && [ -f /app/.env.render ]; then
    echo "Decrypting .env.render..."
    sops --decrypt --input-type dotenv --output-type dotenv /app/.env.render > /app/.env
    set -a
    . /app/.env
    set +a
    echo "Environment loaded from encrypted .env.render"
else
    echo "No SOPS_AGE_KEY or .env.render — using Render dashboard env vars"
fi

exec python -u api/server.py "$@"
