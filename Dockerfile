# syntax=docker/dockerfile:1.6
# ---------- Stage 1: builder ----------
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

ARG TARGETARCH
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m pip install --upgrade pip setuptools wheel

# PyTorch CPU(避免装完整 CUDA 包拉大镜像)
RUN pip install \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
# requirements.txt 面向本地/conda,里面保留 torch 三件套。
# Docker 已在上一步固定安装 CPU 版 PyTorch,这里过滤掉 torch 相关行,
# 避免 pip wheel 重新解析到 CUDA 依赖或重复下载大包。
RUN awk 'BEGIN{IGNORECASE=1} !/^(torch|torchvision|torchaudio)([<>=~! ].*)?$/' requirements.txt > requirements.docker.txt \
    && pip wheel --wheel-dir /wheels -r requirements.docker.txt

# ---------- Stage 2: frontend ----------
FROM node:20-alpine AS frontend-builder

WORKDIR /web

COPY web/package*.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ARG TARGETARCH
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODELSCOPE_CACHE=/home/matrix/.cache/modelscope \
    HF_HOME=/home/matrix/.cache/huggingface \
    TORCH_HOME=/home/matrix/.cache/torch

# 运行时系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 matrix

WORKDIR /app

# 装预编译的 wheels(从 builder 拷过来)
COPY requirements.txt /app/requirements.txt
COPY --from=builder /wheels /wheels
RUN awk 'BEGIN{IGNORECASE=1} !/^(torch|torchvision|torchaudio)([<>=~! ].*)?$/' /app/requirements.txt > /app/requirements.docker.txt \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install --find-links /wheels \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --find-links /wheels -r /app/requirements.docker.txt \
    && rm -rf /wheels /root/.cache /tmp/*
RUN mkdir -p /app/data /app/uploads /app/engine/speaker/speaker_db \
        /home/matrix/.cache/modelscope /home/matrix/.cache/huggingface /home/matrix/.cache/torch \
    && chown -R matrix:matrix /app /home/matrix/.cache

# 拷应用代码
COPY --chown=matrix:matrix . /app
COPY --from=frontend-builder --chown=matrix:matrix /web/dist /app/web/dist
RUN chmod +x /app/docker/entrypoint.sh 2>/dev/null || true

USER matrix
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "main.py"]
