FROM python:3.10-slim

WORKDIR /app

COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only deployed code
COPY config.py .
COPY trading/ trading/
COPY backend/__init__.py backend/__init__.py
COPY backend/news_fetcher.py backend/news_fetcher.py
COPY api/ api/

# State directory
RUN mkdir -p /tmp/jtrader
ENV JTRADER_STATE_DIR=/tmp/jtrader

# Render sets $PORT automatically
CMD ["python", "-u", "api/server.py"]
