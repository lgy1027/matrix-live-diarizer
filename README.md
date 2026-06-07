<div align="center">

# Matrix Live Diarizer

**实时语音转写与说话人识别系统**

基于 Qwen3-ASR 构建,默认数据不外传,支持本地 LLM 增强

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ModelScope](https://img.shields.io/badge/ModelScope-Qwen3--ASR-orange.svg)](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B)

[English](#english) | 简体中文

</div>

---

## ✨ 核心特性

- 🎤 **实时转写** — WebSocket 流式,说话即转写
- 👥 **说话人识别** — CamPlus / ERes2NetV2 / Wespeaker 3 种引擎,API 运行时切换
- 🗂️ **批量管理** — Voice Library 多选 + 批量删除,自动清空 segments 引用
- 📁 **离线处理** — 长音频自动分段 + 重叠合并,SRT/VTT/MD/JSON 导出
- 🤖 **可选 LLM** — 摘要 / 行动项 / 纪要,默认仅本机 Ollama,可显式开公网
- 🔐 **安全默认** — DNS rebinding 防御 + Bearer token 本机 + prompt 注入隔离

## 🚀 30 秒快速开始

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
pip install -r requirements.txt

# 2. 启动(首次需联网下载模型 ~1.8GB)
python main.py

# 3. 浏览器打开 web/index.html(用 file:// 协议)
open web/index.html   # macOS
# 或手动双击 web/index.html
```

启动日志示例:
```
[ASR] 初始化中,设备: mps
[ASR] 模型加载成功(VAD 已启用)
[CamPlus] 引擎初始化完成
INFO:     Uvicorn running on http://0.0.0.0:8000
```

换引擎启动:
```bash
SPEAKER_ENGINE=eres2net python main.py
```

> ⚠️ macOS MPS 偶发加载死锁 → 用 `ASR_DEVICE=cpu python main.py` 启动
> (详见 [常见问题](#-常见问题) Q1)

## 📚 详细文档

| 文档 | 内容 |
|------|------|
| **[docs/USAGE.md](docs/USAGE.md)** | Web 界面详细使用 + 高级场景 + 故障排查 |
| **[docs/API.md](docs/API.md)** | 所有 API 端点(WebSocket/上传/说话人/引擎)+ 环境变量 |
| **[docs/LLM_SETUP.md](docs/LLM_SETUP.md)** | LLM 配置:本地 Ollama / 公网 OpenAI / LiteLLM 反代 |
| **[docs/PRIVACY.md](docs/PRIVACY.md)** | 隐私保证:默认本地 + 可选公网 + 4 道护栏 |
| **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** | 贡献规则:author 必须 lgy1027,commit 禁止 AI 痕迹 |

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
