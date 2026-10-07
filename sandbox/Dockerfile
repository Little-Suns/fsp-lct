# Песочница для задач на код: nsjail + Python 3 + Node 22 (TypeScript через --experimental-strip-types).
# Запускается только privileged (namespaces + cgroup v2 внутри контейнера), см. README «Песочница».
FROM debian:bookworm-slim AS nsjail
RUN apt-get update && apt-get install -y --no-install-recommends \
      autoconf bison flex gcc g++ git ca-certificates libprotobuf-dev libnl-route-3-dev libtool make pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 3.4 https://github.com/google/nsjail /nsjail && make -C /nsjail -j"$(nproc)" && strip /nsjail/nsjail

FROM node:22-bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends python3 libprotobuf32 libnl-route-3-200 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=nsjail /nsjail/nsjail /usr/local/bin/nsjail
WORKDIR /srv/sandbox
COPY entrypoint.sh server.py harness.py harness.mts policy.kafel ./
RUN chmod 755 entrypoint.sh && chmod 644 server.py harness.py harness.mts policy.kafel
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["/srv/sandbox/entrypoint.sh"]
CMD ["python3", "/srv/sandbox/server.py"]

# тесты песочницы против настоящего nsjail: docker build --target test -t fsp-sandbox-test sandbox && docker run --rm --privileged fsp-sandbox-test
FROM runtime AS test
RUN apt-get update && apt-get install -y --no-install-recommends python3-pytest && rm -rf /var/lib/apt/lists/*
COPY tests ./tests
CMD ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

FROM runtime
