# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY engine ./engine
COPY sdk ./sdk
COPY models ./models
COPY renderers ./renderers
COPY protocol ./protocol
RUN chmod -R a+rX /app && pip install --no-build-isolation --no-deps . && useradd --uid 10001 --create-home openape && mkdir /data && chown openape /data
USER 10001:10001
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV OPENAPE_DATA=/data OPENAPE_DECODER=/app/models/decoder-v3/decoder.safetensors PYTHONDONTWRITEBYTECODE=1
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health/ready', timeout=2)"
CMD ["openape", "serve", "--host", "0.0.0.0", "--data", "/data"]
