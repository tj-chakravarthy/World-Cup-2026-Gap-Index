# syntax=docker/dockerfile:1
# Pipeline image, Debian-native (PLAN.md "Full Stack" / Phase 6). Mirrors the
# local dev box (trixie): the scientific/scraping base from apt (apt-packages.txt),
# only the libs Debian doesn't package from pip (requirements.txt). build-essential
# is in the apt list for pytensor (pymc) C++ at runtime.
FROM debian:trixie-slim
WORKDIR /app
COPY apt-packages.txt requirements.txt ./
RUN apt-get update \
    && sed 's/#.*//' apt-packages.txt | xargs apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# --break-system-packages: the container IS the env (PEP 668), and the apt base
# is already in place — pip only adds the unpackaged libs on top of it.
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt
COPY . .
