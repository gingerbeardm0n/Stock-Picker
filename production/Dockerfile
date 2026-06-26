FROM python:3.10-slim

WORKDIR /app

# Install SOPS + age for encrypted env decryption at startup
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sL https://github.com/getsops/sops/releases/download/v3.9.4/sops-v3.9.4.linux.amd64 -o /usr/local/bin/sops \
    && chmod +x /usr/local/bin/sops \
    && curl -sL https://github.com/FiloSottile/age/releases/download/v1.2.0/age-v1.2.0-linux-amd64.tar.gz \
    | tar xz -C /usr/local/bin --strip-components=1 age/age age/age-keygen \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only deployed code
COPY config.py .
COPY trading/ trading/
COPY backend/__init__.py backend/__init__.py
COPY backend/news_fetcher.py backend/news_fetcher.py
COPY api/ api/
COPY scripts/decrypt-and-start.sh /app/decrypt-and-start.sh
RUN chmod +x /app/decrypt-and-start.sh

# Encrypted env file (values encrypted, safe to commit)
COPY .env.render .env.render

# State directory
RUN mkdir -p /tmp/jtrader
ENV JTRADER_STATE_DIR=/tmp/jtrader

# Render sets $PORT automatically
CMD ["/app/decrypt-and-start.sh"]
