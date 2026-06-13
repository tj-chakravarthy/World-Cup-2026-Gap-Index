# syntax=docker/dockerfile:1
# Pipeline image (Python 3.11). Scaffold — see PLAN.md "Full Stack" / Phase 6.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
