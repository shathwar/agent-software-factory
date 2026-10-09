FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1

# Build from repository root; copy only the public runtime and skill distribution.
COPY src/ship /opt/agentflow/src/ship
COPY skills /opt/agentflow/skills
ENV PYTHONPATH=/opt/agentflow/src
