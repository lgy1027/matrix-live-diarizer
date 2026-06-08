<div align="center">

# Matrix Live Diarizer

**本地优先的会议语音 AI · 默认 0 字节外传**

3-10 人小会议 / 个人实时字幕。转写 + 说话人识别 + 摘要纪要，跑在你自己的机器上。
**音频和转写永远不上云**，LLM 可选本机 Ollama 或局域网 vLLM。

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ModelScope](https://img.shields.io/badge/ModelScope-Qwen3--ASR-orange.svg)](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B)

</div>

---

## 30 秒价值主张

> 你的会议录音 → 自动转写 + 说话人识别 + 摘要纪要。
> **默认 0 字节外传**。需要时，你可以接 Ollama / 局域网 vLLM。

## 为什么用 Matrix，不用飞书妙记 / 通义听悟？

|              | 飞书/通义           | Matrix                |
|--------------|--------------------|----------------------|
| 音频上传到云  | ✅ 必须             | ❌ 永远不             |
| 转写速度      | 看网速              | 看显卡                |
| 局域网 LLM   | ❌                  | ✅ 内网 vLLM 即可     |
| 离线运行      | ❌                  | ✅ 完全离线           |
| 费用          | ¥X/人/月            | 一次部署永久免费       |
| 说话人识别    | 通用（易混）         | 手动注册（准）         |
| 数据所有权    | 厂商                | 永远是你              |

## 目标用户

- 🏢 **3-10 人小团队** — 周会 / 产品评审 / 客户沟通，自动出纪要
- 👤 **个人开发者** — 直播 / 课程 / 播客的实时字幕
- 🔒 **律师 / 医生 / 记者** — 录音受法规或行业约束，不能上云
- 🏠 **局域网 AI 用户** — 已有 vLLM / Ollama，想把转写接上

## 🐳 Docker 快速开始(推荐)

无需装 PyTorch,5 分钟跑通。

```bash
# 1. 克隆 + 启动
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
docker compose up -d

# 2. 看日志(首次启动会下载 ASR 模型 ~1.8GB,5-20 分钟)
docker compose logs -f

# 3. 浏览器打开前端
open web/index.html               # macOS
# Linux/Windows:双击 web/index.html
```

**特性:**
- 镜像 ~800MB,模型按需下载(不进镜像,避免 ImagePullBackOff)
- 数据持久化在 docker volume,删容器不丢
- 支持 linux/amd64 + linux/arm64(M1/M2 Mac 也能跑)
- 健康检查 + 非 root 用户运行

> 需要换架构加速构建?`docker buildx create --use` 配远程构建。

## 🚀 5 分钟跑通(从源码)

```bash
# 1. 装依赖
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
pip install -r requirements.txt

# 2. 启动(首次需联网下载模型 ~1.8GB,完了可断网)
ASR_DEVICE=cpu python main.py     # MPS 死锁时用 CPU
# 或:python main.py                # M 系列 Mac 默认 MPS

# 3. 浏览器打开前端
open web/index.html               # macOS
# Linux/Windows:双击 web/index.html
```

启动后看到 `Uvicorn running on http://0.0.0.0:8000` 即成功。
前端是纯静态文件,用 `file://` 打开会自动连 `ws://127.0.0.1:8000`。

## ✨ 它能做什么

- 🎤 **实时转写** — 浏览器录音，WebSocket 流式，说话即出文字
- 📁 **离线处理** — 上传录音文件，自动分段 + 说话人识别，导出 SRT / VTT / MD / JSON
- 👥 **说话人识别** — 手动注册声纹，会议里自动标"张三说的"
- 🤖 **可选 LLM** — 摘要 / 行动项 / 会议纪要；默认关，启用时支持 Ollama / 局域网 vLLM / OpenAI 兼容 endpoint
- 🛡️ **离线兜底** — LLM 未配时自动用 TextRank 提取本地摘要,不出错也不空白
- 📚 **历史会话** — 所有转写本地存库（SQLite），随时回看
- 🔐 **安全默认** — DNS rebinding 防御 + 仅本机改 LLM 配置 + prompt 注入隔离

## 📚 详细文档

| 文档 | 内容 |
|------|------|
| **[docs/USAGE.md](docs/USAGE.md)** | Web 界面详细使用 + 高级场景 + 故障排查 |
| **[docs/API.md](docs/API.md)** | 所有 API 端点（WebSocket/上传/说话人/引擎）+ 环境变量 |
| **[docs/LLM_SETUP.md](docs/LLM_SETUP.md)** | LLM 配置：本地 Ollama / 公网 OpenAI / 局域网 vLLM |
| **[docs/PRIVACY.md](docs/PRIVACY.md)** | 隐私保证：默认本地 + 可选远程 + 4 道护栏 |

## 🎯 声纹引擎对比

| 引擎 | EER (VoxCeleb) | EER (CNCeleb) | 参数量 | 速度 | 适用场景 |
|:----:|:--------------:|:-------------:|:------:|:----:|:--------:|
| **CamPlus** | 0.65% | 6.78% | 7.2M | ⚡ 快 | 实时场景 (默认) |
| **ERes2NetV2** | 0.61% | 6.14% | 17.8M | 🚗 中 | 高精度需求 |
| **Wespeaker** | 1.05% | 6.92% | 6.34M | ⚡ 快 | 经典稳定 |

## 🏗️ 项目结构

```
matrix-live-diarizer/
├── main.py                # 入口
├── app/                   # FastAPI 应用层
│   ├── api/               # websocket / upload / speakers / health
│   ├── repositories/      # SQLite 持久化
│   ├── services/          # LLM / exporter / statistics
│   ├── middleware/        # 速率限制
│   └── config.py          # 配置 dataclass
├── engine/                # 推理引擎层
│   ├── asr_engine.py      # Qwen3-ASR + Silero VAD
│   └── speaker/           # 3 种声纹引擎 + factory
├── tests/                 # 239 个测试(包含 smoke test)
├── docs/                  # 详细文档
│   ├── USAGE.md           # 使用指南
│   ├── API.md             # API 参考
│   ├── LLM_SETUP.md       # LLM 配置
│   └── PRIVACY.md         # 隐私保证
└── web/index.html         # Web SPA(实时/历史/声纹/设置)
```

## 📦 模型来源

| 模块 | 模型 | 来源 |
|------|------|------|
| ASR | [Qwen3-ASR-0.6B](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B) | ModelScope |
| Speaker | CamPlus / ERes2NetV2 / Wespeaker | ModelScope |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | torch.hub |

首次启动自动下载,完成后**永久断网可用**(LLM 关闭时)。

## ⚠️ 注意事项

- **单进程运行** — Mac MPS 必须 `WORKERS=1`,避免内存溢出
- **采样率 16kHz** — 浏览器自动重采样,API 客户端需注意
- **文件上传** — 500MB 上限,1 小时时长上限
- **首次启动** — 需联网下载模型约 1.8GB

## 🎬 试用示例数据

clone 完不知道这玩意能干嘛?一条命令注入 2 个示例转写:

```bash
# 首次会下载 ~5MB CC0 音频(Stanford 公开讲座 + LibriVox 朗读)
# 然后自动跑转写,2-5 分钟
python scripts/seed_demo_data.py

# 删掉重置
python scripts/seed_demo_data.py --force

# 不想下载,只插空 session
python scripts/seed_demo_data.py --no-audio
```

完成后打开 `web/history.html` 看到 2 条"示例: ..."会话。
**注意**: 示例是公开讲座和朗读片段,不是会议录音 — 用来体验转写+说话人识别功能。

## ❓ 常见问题

**Q1: `python main.py` 卡住不动 4+ 分钟?**
A: macOS MPS 加载 Qwen3-ASR 偶发死锁。已加 90s 超时回退 CPU。
   手动:`ASR_DEVICE=cpu python main.py`

**Q2: 想清理大量重复 / 低质量声纹?**
A: Voice Library 点 **Select** → 多选 → **Delete N**。
   或 API:`POST /v1/speakers/cleanup`(`docs/API.md` 第 3 节)。

**Q3: 想用 GPT-4 / Claude 质量但保持隐私?**
A: 本地起 [LiteLLM](https://github.com/BerriAI/litellm) 反代,
   Matrix 通过 `http://127.0.0.1:4000` 访问(无需 `LLM_ALLOW_PUBLIC`)。
   详见 [`docs/LLM_SETUP.md`](docs/LLM_SETUP.md)。

**Q4: 数据会发到云端吗?**
A: 默认**不会**。LLM 公网 endpoint 需**显式**设 `LLM_ALLOW_PUBLIC=true` 才放行,
   且只发转写文本到指定 endpoint,不包含音频和声纹向量。
   详见 [`docs/PRIVACY.md`](docs/PRIVACY.md)。

更多问题见 [docs/USAGE.md 故障排查](docs/USAGE.md#故障排查速查)。

## 🤝 贡献

欢迎 Issue 和 PR！

1. Fork 仓库
2. 创建分支 (`git checkout -b feature/AmazingFeature`)
3. 提交 (`git commit -m 'feat: add some amazing feature'`)
4. 推送 (`git push origin feature/AmazingFeature`)
5. 提 Pull Request

## 📄 License

[MIT](LICENSE)

---

<div align="center">

**如果这个项目对你有帮助,请给一个 ⭐ Star 支持!**

</div>
