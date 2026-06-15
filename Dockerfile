# syntax=docker/dockerfile:1
# Live-cron image, Debian-native (PLAN.md "Full Stack" / Phase 6). Mirrors the
# local dev box (trixie): the scientific/scraping base from apt (apt-packages.txt),
# plus only the pip-gap the cron's run_all chain needs (requirements-runtime.txt =
# pyarrow). The full data-prep stack (requirements.txt: socceraction/pymc/...) is
# NOT installed here — socceraction has no py3.13 wheel and none of it runs in the
# cron; that prep happens offline on the dev boxes. build-essential stays in the apt
# list (harmless; kept so the image still mirrors the dev base).
FROM debian:trixie-slim
WORKDIR /app
COPY apt-packages.txt requirements-runtime.txt ./
RUN apt-get update \
    && sed 's/#.*//' apt-packages.txt | xargs apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# --break-system-packages: the container IS the env (PEP 668), and the apt base
# is already in place — pip only adds the unpackaged libs on top of it.
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements-runtime.txt
COPY . .
