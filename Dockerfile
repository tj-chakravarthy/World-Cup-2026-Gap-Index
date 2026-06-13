# syntax=docker/dockerfile:1
# Pipeline image (Python 3.11). Scaffold — see PLAN.md "Full Stack" / Phase 6.
FROM python:3.11-slim
WORKDIR /app
# slim has no compiler, and pytensor (pymc) wants to build C++ at runtime
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
