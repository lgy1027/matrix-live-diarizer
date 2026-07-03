# LLM 设置指南

LLM 高级功能（摘要、行动项、会议纪要）支持 **OpenAI 兼容接口**（`/chat/completions`）。
默认仅本机，可显式开公网。

---

## 方式 1：本地 Ollama（默认，隐私优先）

### 1. 安装 Ollama

```bash
# macOS
brew install ollama
# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. 拉取模型

```bash
# 默认推荐（小、快、CPU 可跑）
ollama pull qwen2.5:1.5b

# 或更高质量（需要 8GB+ 内存）
ollama pull qwen2.5:7b
```

### 3. 启动服务

```bash
ollama serve
# 默认监听 http://127.0.0.1:11434
```

### 4. 配置 Matrix（.env）

```bash
LLM_ENABLED=true
LLM_ENDPOINT=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:1.5b
# 不需要 LLM_API_KEY（本机 Ollama 不鉴权）
```

---

## 方式 2：公网 OpenAI 兼容接口（需显式开公网）

支持 **OpenAI / DeepSeek / 智谱 / 月之暗面 / OpenRouter / LiteLLM 反代** 等任何 `/chat/completions` 兼容端点。

### ⚠️ 警告

开公网后,转写文本会离开你的电脑发送到第三方 LLM 服务。
**默认行为不变（仅本机）** — 你必须**显式**设置 `LLM_ALLOW_PUBLIC=true` 才会启用。

### 配置示例：OpenAI

```bash
LLM_ENABLED=true
LLM_ALLOW_PUBLIC=true                           # ← 显式开公网
LLM_ENDPOINT=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
```

### 配置示例：DeepSeek

```bash
LLM_ENABLED=true
LLM_ALLOW_PUBLIC=true
LLM_ENDPOINT=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-xxx
```

### 配置示例：LiteLLM 反代（推荐！本地包公网）

如果你想使用公网高质量大模型又不想让转写文本直接离开本机,
可以用 [LiteLLM](https://github.com/BerriAI/litellm) 在本机起反代:

```bash
pip install 'litellm[proxy]'
# litellm.yaml (key 放本机,不直接暴露给 Matrix)
cat > litellm.yaml <<'EOF'
model_list:
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
EOF
litellm --config litellm.yaml   # 监听 127.0.0.1:4000
```

```bash
# Matrix .env
LLM_ENABLED=true
LLM_ENDPOINT=http://127.0.0.1:4000           # 本机,不需要 LLM_ALLOW_PUBLIC
LLM_MODEL=gpt-4o-mini
# LLM_API_KEY 不需要,key 在 LiteLLM 配置里
```

---

## 前端配置

打开 `web/index.html` → 左侧菜单 **Settings** → LLM 区块：
- 勾选"启用 LLM"
- 状态显示 "✅ 可用"（如果 endpoint 通）

详细字段配置在 `.env` 文件（不通过 UI 配置）。

> ⚠️ **生产环境部署**:如果你把 Matrix 放在 nginx/Cloudflare 后面,
> **不要**依赖 X-Forwarded-For 做限流/审计 — 详见
> [`app/middleware/rate_limit.py`](../app/middleware/rate_limit.py) 里的
> `trusted_proxies` 配置(默认只信任 127.0.0.0/8)。

---

## 环境变量参考

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_ENABLED` | `false` | 是否启用 LLM 功能 |
| `LLM_ENDPOINT` | `http://127.0.0.1:11434/v1` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | `qwen2.5:1.5b` | 模型名 |
| `LLM_API_KEY` | (空) | Bearer token,公网 OpenAI 等需要 |
| `LLM_TIMEOUT_SEC` | `60` | 单次请求超时 |
| `LLM_MAX_INPUT_TOKENS` | `8000` | 输入上限(超长截断) |
| `LLM_MOCK` | `false` | mock 模式,返回固定文本不真调 LLM |
| `LLM_ALLOW_PUBLIC` | `false` | **安全开关**:允许公网 endpoint,默认拒绝 |
| `LLM_ALLOWED_HOSTS` | `127.0.0.1,::1,localhost` | 总是放行的 host 白名单(无需 allow_public) |

---

## 推荐模型

| 模型 | 内存 | 速度 | 质量 |
|---|---|---|---|
| qwen2.5:0.5b | 1GB | ⚡⚡⚡ | ★★ |
| qwen2.5:1.5b | 3GB | ⚡⚡ | ★★★ |
| qwen2.5:7b | 8GB | ⚡ | ★★★★ |
| llama3.2:3b | 4GB | ⚡⚡ | ★★★ |
| gpt-4o-mini (云) | 0 (按量) | ⚡ | ★★★★ |
| deepseek-chat (云) | 0 (按量) | ⚡⚡ | ★★★★ |

## 隐私

**默认行为**:
- 你的转写文本**不会**发送到 Ollama 以外的任何地方
- Ollama 本身只在你本机运行
- 第一次配置后无需联网

**显式开公网后**:
- 转写文本会发到 `LLM_ENDPOINT` 指向的服务
- API Key 仅存在本机 `.env`,Matrix 不上报任何 key
- 关闭:把 `LLM_ENABLED=false` 即可

## 故障排查

**"❌ 不可用"**：
- 确认 LLM 服务在运行：`curl $LLM_ENDPOINT/models`
- 确认模型已下载（Ollama: `ollama list`，OpenAI: 账户有访问权限）
- 确认 Matrix 的 endpoint 与服务监听地址一致

**`EndpointSecurityError`**：
- 你配了公网 endpoint 但没设 `LLM_ALLOW_PUBLIC=true`
- 解决:加 `LLM_ALLOW_PUBLIC=true` 到 `.env`

**`404 model not found`**：
- Ollama: 没拉模型,`ollama pull <model>`
- OpenAI: model 名拼写错,或账户无访问权限

**`504 timeout`**：
- 模型太大,改小或加 `LLM_TIMEOUT_SEC=120`

**`401 unauthorized`**：
- `LLM_API_KEY` 没配或配错
