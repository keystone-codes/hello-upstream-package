# python:3.12-slim
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

RUN groupadd --system --gid 10001 hello \
    && useradd --system --uid 10001 --gid hello \
       --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin hello

WORKDIR /app
COPY requirements.txt server.py keystone_identity.py ./

RUN pip install --no-cache-dir --require-hashes -r requirements.txt

USER hello:hello
EXPOSE 8081

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz')"]

CMD ["python", "server.py"]
