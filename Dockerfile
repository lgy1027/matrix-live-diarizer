# syntax=docker/dockerfile:1.6
# ---------- Stage 1: builder ----------
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

ARG TARGETARCH

# 编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# PyTorch CPU(避免装完整 CUDA 包拉大镜像)
RUN pip install --no-cache-dir \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ARG TARGETARCH

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
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --find-links /wheels \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --find-links /wheels -r /app/requirements.txt 2>/dev/null || true \
    && rm -rf /wheels /root/.cache

# 拷应用代码
COPY --chown=matrix:matrix . /app
RUN chmod +x /app/docker/entrypoint.sh 2>/dev/null || true

USER matrix
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "main.py"]
