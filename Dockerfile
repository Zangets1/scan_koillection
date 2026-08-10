FROM python:3.12-slim AS base

# Renseigné par le workflow de release avec le tag Git (ex. « v1.0.0 »).
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    PUID=10001 \
    PGID=10001

WORKDIR /app

# Les dépendances sont installées avant le code : la couche reste en cache
# tant que requirements.txt ne change pas.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# L'application n'écrit que dans /data. Le point d'entrée s'occupe d'aligner le
# propriétaire du volume puis abandonne les privilèges root.
RUN groupadd --gid 10001 scan \
 && useradd --system --uid 10001 --gid 10001 --create-home scan \
 && mkdir -p /data \
 && chown -R scan:scan /data \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
