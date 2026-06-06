# 本地 LLM 设置指南

让 LLM 高级功能（摘要、行动项、会议纪要）需要本地 LLM 服务。

## 1. 安装 Ollama

```bash
# macOS
brew install ollama
# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

## 2. 拉取模型

```bash
# 默认推荐（小、快、CPU 可跑）
ollama pull qwen2.5:1.5b

# 或更高质量（需要 8GB+ 内存）
ollama pull qwen2.5:7b
```

## 3. 启动服务

```bash
ollama serve
# 默认监听 http://127.0.0.1:11434
```

## 4. 配置 Matrix

在 `web/settings.html` 中：
- 勾选"启用 LLM"
- Endpoint: `http://127.0.0.1:11434/v1`（默认）
- 模型: `qwen2.5:1.5b`（或你下载的）
- 点击"测试连接" → 状态显示"✅ 可用"

## 推荐模型

| 模型 | 内存 | 速度 | 质量 |
|---|---|---|---|
| qwen2.5:0.5b | 1GB | ⚡⚡⚡ | ★★ |
| qwen2.5:1.5b | 3GB | ⚡⚡ | ★★★ |
| qwen2.5:7b | 8GB | ⚡ | ★★★★ |
| llama3.2:3b | 4GB | ⚡⚡ | ★★★ |

## 隐私

- 你的转写文本**不会**发送到 Ollama 以外的任何地方
- Ollama 本身只在你本机运行
- 第一次配置后无需联网

## 故障排查

**"❌ 不可用"**：
- 确认 `ollama serve` 在运行：`curl http://127.0.0.1:11434/v1/models`
- 确认模型已下载：`ollama list`
- 确认 Matrix 的 endpoint 与 Ollama 监听地址一致
