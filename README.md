<div align="center">

# Matrix Live Diarizer

**本地优先的会议语音 AI · 默认 0 字节外传**

面向个人实时字幕、单人/双人录音转写，以及小团队会议录音的本地 AI 处理工具。
实时模式适合低延迟字幕和参考性说话人标签；多人会议高准确度归档建议上传完整录音并启用离线 diarization。
**音频和转写默认不上云**，ASR / 声纹 / LLM 都可以在设置页按需切换。

> 产品边界：**实时模式**主打低延迟字幕和参考性说话人标签；**上传离线模式**可在完整音频上做更高准确度的 pyannote diarization。单麦克风实时多人识别只能作为辅助参考，不等同于云会议产品的离线后处理结果。

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ModelScope](https://img.shields.io/badge/ModelScope-Qwen3--ASR-orange.svg)](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B)
[![Status](https://img.shields.io/badge/status-v0.3.0--beta-orange.svg)](#)

**中文** | [English](README.en.md)

> 当前版本为 **v0.3.0-beta**：适合本地试用、个人工作流和小团队内网部署验证；不建议直接作为公网生产服务裸露部署。

</div>

---

## 30 秒价值主张

> 你的会议录音 → 自动转写 + 说话人识别 + 摘要纪要。
> **默认 0 字节外传**。需要时，你可以接 Ollama / LM Studio / 局域网 vLLM / OpenAI-compatible endpoint。

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

- 🏢 **小团队会议录音** — 周会 / 产品评审 / 客户沟通，上传后自动转写和整理纪要
- 👤 **个人开发者** — 直播 / 课程 / 播客的实时字幕
- 🔒 **律师 / 医生 / 记者** — 录音受法规或行业约束，不能上云
- 🏠 **局域网 AI 用户** — 已有 vLLM / Ollama，想把转写接上

## 🐳 Docker 快速开始(推荐)

无需在宿主机安装 PyTorch。Docker 镜像默认使用 **CPU 版 PyTorch**,模型和数据都挂载到 Docker volume,删除容器不丢。

```bash
# 1. 克隆
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer

# 2. 可选:使用 .env 覆盖默认配置
# 不复制也能启动;复制后可修改 ASR_ENGINE / LLM_ENDPOINT / PORT 等
cp .env.example .env

# 如果容器需要访问宿主机 Ollama,不要用 127.0.0.1,改成:
# LLM_ENABLED=true
# LLM_ENDPOINT=http://host.docker.internal:11434/v1

# 3. 构建并启动
docker compose up -d

# 4. 看日志(首次启动会下载 ASR / VAD / 声纹模型,5-20 分钟)
docker compose logs -f

# 5. 浏览器打开前端
# 默认地址: http://127.0.0.1:8000/
# 如果 .env 里改了 PORT=8888,则打开 http://127.0.0.1:8888/
```

**特性:**
- 模型按需下载,不打进镜像
- 持久化卷包含 SQLite 数据、上传文件、说话人库、ModelScope / HuggingFace / Torch 缓存
- 本地 `docker compose up -d` 按当前机器架构构建,支持 linux/amd64 与 linux/arm64
- `docker-compose.yml` 会可选读取 `.env`;`PORT` 会同时控制容器监听端口和宿主机映射端口
- 健康检查 + 非 root 用户运行

常用命令:

```bash
# 重建镜像
docker compose build --pull

# 停止服务但保留模型/数据
docker compose down

# 连 volume 一起删除(会清空模型缓存和历史数据)
docker compose down -v
```

> 需要发布多架构镜像时再使用 buildx,例如:
> `docker buildx build --platform linux/amd64,linux/arm64 -t your-name/matrix-live-diarizer:latest --push .`
>
> Docker 默认镜像是 CPU 版。需要 NVIDIA GPU 时,建议基于 CUDA PyTorch 镜像单独构建 GPU 版,并在 compose 中增加 `gpus: all`。

## 🚀 5 分钟跑通(从源码)

```bash
# 1. 装依赖
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
pip install -r requirements.txt

# 2. 构建前端(Vue/Vite)
cd web
npm ci
npm run build
cd ..

# 3. 启动后端(首次需联网下载模型 ~1.8GB,完了可断网)
ASR_DEVICE=cpu python main.py     # MPS 死锁时用 CPU
# 或:python main.py                # M 系列 Mac 默认 MPS

# 4. 浏览器打开前端
# http://127.0.0.1:8000/
```

启动后看到 `Uvicorn running on http://0.0.0.0:8000` 即成功。
生产模式下 FastAPI 会托管 `web/dist` 中的 Vue SPA。

前端开发模式:

```bash
# 终端 1:后端
python main.py

# 终端 2:前端
cd web
npm ci
npm run dev
# 打开 http://127.0.0.1:5173/
```

如果后端不是 8000 端口,在 `web/.env.local` 里配置:

```bash
VITE_BACKEND_URL=http://127.0.0.1:8888
# 可选。不写会由 VITE_BACKEND_URL 自动推导
# VITE_BACKEND_WS=ws://127.0.0.1:8888
```

## ✨ 它能做什么

- 🎤 **实时转写** — 浏览器录音，WebSocket 流式，说话即出文字
- 📁 **离线处理** — 上传录音文件，自动分段 + 可选 pyannote 离线说话人分离，导出 SRT / VTT / MD / JSON
- 🧠 **多 ASR 引擎** — Qwen3-ASR / SenseVoice / Paraformer / Paraformer Streaming，可在设置页动态切换
- 👥 **说话人识别** — 独立声纹/diarization 流水线，不是 ASR 模型自带能力；实时多人标签仅作参考
- 🔁 **声纹引擎切换** — CamPlus / ERes2NetV2 / Wespeaker，设置页确认后热切换
- 🤖 **可选 LLM** — 摘要 / 行动项 / 会议纪要；设置页支持 Ollama / LM Studio / LocalAI / vLLM / OpenAI-compatible provider
- 🛡️ **离线兜底** — LLM 未配时自动用 TextRank 提取本地摘要,不出错也不空白
- 📚 **历史会话** — 所有转写本地存库（SQLite），随时回看
- 🔐 **JWT 鉴权** — 默认 `admin/admin`, 首次登录强制改密; 全部 `/v1/*` 需 Bearer token (roadmap 安全项)
- 🛡️ **安全默认** — DNS rebinding 防御 + 仅本机改 LLM 配置 + prompt 注入隔离
- 📱 **移动端响应式** — < 768px 自动改底部 tab bar,手机/平板可用(roadmap #1.5)

## ⚙️ 设置页支持

当前设置页不是只读展示,已经支持以下运行时配置:

| 配置 | 页面能力 | 行为 |
|------|----------|------|
| ASR 引擎 | 动态切换 | 新模型未下载时后端会先下载/加载;完成前继续使用旧 ASR |
| 声纹引擎 | 确认弹窗后切换 | 切换 CamPlus / ERes2NetV2 / Wespeaker |
| Local LLM | 修改 provider / endpoint / model / API Key | 页面保存后写入本地 SQLite settings,无需重启 |
| 历史存储 | 状态展示 | 由 `STORAGE_HISTORY_ENABLED` 环境变量控制 |

`.env` 仍然是默认配置来源;只要页面保存过 LLM 设置,页面配置会覆盖 `.env` 中的 LLM 默认值。

## 🔐 鉴权 (Roadmap 安全项)

- 首次启动自动建默认账户 `admin/admin`
- 登录后**强制弹窗**改密,改完才能用其他功能
- 全部 `/v1/*` 端点需 `Authorization: Bearer <token>` header
- Token 默认 24h 有效(JWT HS256, 存 `localStorage`)

**生产部署前必检**:
- 设 `JWT_SECRET` 环境变量(否则 token 跨重启失效)
- 用 HTTPS(JWT 明文有中间人风险)
- 改 `ALLOWED_ORIGINS` 为具体域名(默认 `*`)

详见 **[docs/SECURITY.md](docs/SECURITY.md)**。

## 🎯 能力矩阵 — 说话人识别（重要！）

本项目 **说话人识别能力受架构限制**，不同场景准确度差异很大，请按需选择:

| 场景 | 准确度 | 推荐模式 | 说明 |
|---|---|---|---|
| **单人独白**（网课/播客/直播字幕） | **95%+** | 实时 (WebSocket) | CamPlus 单人 embedding 稳定,推荐主场景 |
| **2-3 人会议**（安静环境/每人说话 ≥ 2s） | **60-80%** | 实时 (WebSocket) | 短段 cosine 波动大,需手动 enroll 提高准确度 |
| **3-10 人会议**（单麦克风 + 多人重叠） | **40-60%** best-effort | 实时 仅作参考 | 单麦克风物理限制,**不建议生产级依赖** |
| **3-10 人会议**（多麦克风 enroll） | **85%+** | 实时 + 强制 enroll | 每人独立麦 + 主动注册声纹 |
| **3-10 人会议**（**离线高准确度**） | **80%+ DER** | 上传文件 + `?diarization=pyannote` | 集成 pyannote 3.1,适合归档前整理 |

**核心限制**：
- 单麦克风无法做声源分离（beamforming 需要硬件麦克风阵列）
- 实时模式 ASR 必须 0.5-5s 出结果,没有长上下文可聚类
- Qwen3-ASR 假设"一段一人",多人重叠直接丢失
- 说话人识别由 CamPlus/ERes2NetV2/Wespeaker 或离线 pyannote 完成,不是 ASR 自带功能

**推荐用法**：
- 想做**多人精确区分**：用多麦克风 OR 上传录音跑离线 pyannote
- 想做**实时字幕**：单人独白/主播用实时模式效果好;多人会议用实时模式做参考性字幕
- 详见 **[docs/SPEAKER_DIARIZATION.md](docs/SPEAKER_DIARIZATION.md)**

## 📚 详细文档

| 文档 | 内容 |
|------|------|
| **[docs/USAGE.md](docs/USAGE.md)** | Web 界面详细使用 + 高级场景 + 故障排查 |
| **[docs/SPEAKER_DIARIZATION.md](docs/SPEAKER_DIARIZATION.md)** | 说话人识别能力边界 + 实时 vs 离线模式选择 |
| **[docs/API.md](docs/API.md)** | 所有 API 端点（WebSocket/上传/说话人/引擎）+ 环境变量 |
| **[docs/LLM_SETUP.md](docs/LLM_SETUP.md)** | LLM 配置：本地 Ollama / 公网 OpenAI / 局域网 vLLM |
| **[docs/PRIVACY.md](docs/PRIVACY.md)** | 隐私保证：默认本地 + 可选远程 + 4 道护栏 |
| **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | 启动、模型、局域网、字级时间戳等常见问题 |

## 📱 移动端使用

同一局域网内访问后端托管的前端地址即可:
- **< 768px** 自动改底部 tab bar(实时/历史/说话人/设置),不再挤 56px 左侧栏
- **< 480px** 极窄屏额外压缩字体和 stat 卡片
- 录音、说话人识别、SRT 导出等所有功能在移动端可用
- 注意: Web 端录音需 HTTPS 或 `localhost`/`file://` — 局域网手机访问后端需配置 CORS(`ALLOWED_ORIGINS` env,详见 `docs/USAGE.md`)

## 🧠 ASR 引擎选择

| 引擎 | 模型 | 依赖 | 推荐场景 |
|------|------|------|----------|
| **Qwen3-ASR** | `Qwen/Qwen3-ASR-0.6B` | `qwen-asr` | 默认高质量中文/多语言转写 |
| **SenseVoice-Small** | `iic/SenseVoiceSmall` | `funasr` | 更轻快的多语种上传转写 |
| **Paraformer** | `paraformer-zh` | `funasr` | 中文会议/访谈离线转写 |
| **Paraformer Streaming** | `paraformer-zh-streaming` | `funasr` | 低延迟实时字幕 |

### 能力矩阵 — 以后端 `/v1/models` 为准

设置页不会硬编码 ASR 能力,而是统一读取后端 `/v1/models` 返回的 `asr_engines`。如果你的部署关闭了某个能力,或者自定义了某个模型适配器,可以通过 `ASR_CAPABILITIES_JSON` 或 `ASR_CAPABILITIES_FILE` 覆盖后端返回的能力说明。

默认分工如下:
- ASR 负责语音转文字,不负责说话人识别。
- Speaker Engine 负责实时参考性声纹标签。
- pyannote 负责上传文件后的离线高准确度 diarization。
- Paraformer Streaming 当前只接入为服务端分段刷新,还不是 token-level 真流式逐 token 输出。

设置页可以动态切换 ASR。若目标模型或依赖尚未就绪,后端会返回明确提示;模型下载/加载完成前旧 ASR 会继续工作。

能力差异提示:
- **word timestamps / 字级时间戳** 仅 Qwen3-ASR + `ASR_WORD_TIMESTAMPS=true` 路径支持;FunASR 系列当前按段落结果展示。
- **Paraformer Streaming** 适合低延迟字幕,但当前接入不是 token-level 真流式逐 token 输出,仍会按服务端语音段刷新。
- **说话人识别** 与 ASR 引擎解耦:切换 ASR 不会让模型本身具备 diarization,实时声纹由 Speaker Engine 完成,上传高准确度 diarization 走 pyannote。

> Windows + Python 3.13 下 `funasr` 可能因为 `editdistance` wheel 缺失安装失败。建议使用 Python 3.10-3.12 或 Docker 环境启用 FunASR 系列引擎。

## 🎯 声纹引擎对比

| 引擎 | EER (VoxCeleb) | EER (CNCeleb) | 参数量 | 速度 | 适用场景 |
|:----:|:--------------:|:-------------:|:------:|:----:|:--------:|
| **CamPlus** | 0.65% | 6.78% | 7.2M | ⚡ 快 | 实时场景 (默认) |
| **ERes2NetV2** | 0.61% | 6.14% | 17.8M | 🚗 中 | 高精度需求 |
| **Wespeaker** | 1.05% | 6.92% | 6.34M | ⚡ 快 | 经典稳定 |

声纹引擎也可在设置页热切换。切换前会显示确认弹窗,避免识别过程中误切。

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
│   ├── asr_engine.py      # Qwen3-ASR 兼容层 + Silero VAD
│   ├── asr/               # ASR 工厂 + FunASR 引擎 + 动态切换管理器
│   └── speaker/           # 3 种声纹引擎 + factory + 动态切换管理器
├── tests/                 # 单元测试 / API 测试 / smoke test
├── docs/                  # 详细文档
│   ├── USAGE.md           # 使用指南
│   ├── API.md             # API 参考
│   ├── LLM_SETUP.md       # LLM 配置
│   └── PRIVACY.md         # 隐私保证
└── web/                   # Vue/Vite 前端
    ├── src/               # SPA 源码(实时/历史/声纹/设置)
    └── dist/              # npm run build 后生成,由 FastAPI 托管
```

## 📦 模型来源

| 模块 | 模型 | 来源 |
|------|------|------|
| ASR | Qwen3-ASR / SenseVoice / Paraformer | ModelScope |
| Speaker | CamPlus / ERes2NetV2 / Wespeaker | ModelScope |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | torch.hub |

首次使用某个模型时自动下载,完成后缓存到本机或 Docker volume。LLM 关闭且模型已缓存时,核心转写能力可离线使用。

## ⚠️ 注意事项

- **单进程运行** — Mac MPS 必须 `WORKERS=1`,避免内存溢出
- **采样率 16kHz** — 浏览器自动重采样,API 客户端需注意
- **文件上传** — 500MB 上限,1 小时时长上限
- **首次启动** — 需联网下载默认 ASR / VAD / 声纹模型
- **动态切换** — ASR / 声纹切换会加载新模型,首次切换耗时取决于网络和磁盘缓存

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

完成后打开 `http://127.0.0.1:8000/library` 看到 2 条"示例: ..."会话。
**注意**: 示例是公开讲座和朗读片段,不是会议录音 — 用来体验转写+说话人识别功能。

## ❓ 常见问题

**Q1: `python main.py` 卡住不动 4+ 分钟?**
A: macOS MPS 加载 Qwen3-ASR 偶发死锁。已加 90s 超时回退 CPU。
   手动:`ASR_DEVICE=cpu python main.py`

**Q2: 想清理大量重复 / 低质量声纹?**
A: Voice Library 点 **Select** → 多选 → **Delete N**。
   或 API:`POST /v1/speakers/cleanup`(`docs/API.md` 第 3 节)。

**Q3: 想用公网高质量大模型但保持隐私?**
A: 推荐本地起 [LiteLLM](https://github.com/BerriAI/litellm) 反代,
   然后在设置页选择 `Custom`,填 `http://127.0.0.1:4000/v1`。
   也可以在 `.env` 中写 `LLM_ENDPOINT`,但页面保存后的 LLM 配置优先生效。
   详见 [`docs/LLM_SETUP.md`](docs/LLM_SETUP.md)。

**Q4: 数据会发到云端吗?**
A: 默认**不会**。LLM 公网 endpoint 需**显式**设 `LLM_ALLOW_PUBLIC=true` 才放行,
   且只发转写文本到指定 endpoint,不包含音频和声纹向量。
   详见 [`docs/PRIVACY.md`](docs/PRIVACY.md)。

**Q5: 前端开发服务怎么连不同后端端口?**
A: 在 `web/.env.local` 配置 `VITE_BACKEND_URL=http://127.0.0.1:8888`。
   WebSocket 地址默认会自动从这个 URL 推导,通常不用单独配 `VITE_BACKEND_WS`。

**Q6: Docker 里为什么访问不了宿主机 Ollama?**
A: 容器内的 `127.0.0.1` 是容器自己。请使用
   `LLM_ENDPOINT=http://host.docker.internal:11434/v1`,compose 已内置 `extra_hosts`。

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
