# python:3.12-slim
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
