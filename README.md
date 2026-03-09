<div align="center">

# Matrix Live Diarizer

**实时语音转写与说话人识别系统**

基于 Qwen3-ASR 构建，支持 WebSocket 流式传输与多声纹引擎切换

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ModelScope](https://img.shields.io/badge/ModelScope-Qwen3--ASR-orange.svg)](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B)

[English](#english) | 简体中文

</div>

---

## ✨ 特性

- 🎤 **实时转写** - WebSocket 流式传输，说话即转写，低延迟响应
- 👥 **说话人识别** - 自动区分不同说话人，支持增量学习
- 🔧 **多引擎支持** - CamPlus / ERes2NetV2 / Wespeaker 三种声纹引擎可切换
- 📁 **离线处理** - 支持上传音频文件批量处理
- 🎯 **智能 VAD** - Silero VAD 语音活动检测，精准识别语音段
- 🧹 **幻觉过滤** - 自动过滤 ASR 常见幻觉输出，提升准确性

## 🚀 快速开始

### 环境要求

- Python 3.12+
- PyTorch 2.0+ (支持 CUDA / MPS / CPU)

### 安装

```bash
# 克隆项目
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer

# 安装依赖
pip install -r requirements.txt
```

### 启动服务

```bash
# 默认使用 CamPlus 引擎
python main.py

# 使用 ERes2NetV2 高精度引擎
SPEAKER_ENGINE=eres2net python main.py

# 使用 Wespeaker 引擎
SPEAKER_ENGINE=wespeaker python main.py
```

服务启动后访问 **http://127.0.0.1:8000**

<details>
<summary>📊 查看启动日志示例</summary>

```
[FACTORY] 使用 CamPlus 引擎
[ASR] 初始化中，设备: mps
[ASR] 模型加载成功（VAD 已启用）
[CamPlus] 引擎初始化完成
声纹引擎: CamPlus, 模型: damo/speech_campplus_sv_zh-cn_16k-common
INFO:     Uvicorn running on http://0.0.0.0:8000
```

</details>

## 📖 使用指南

### Web 界面

访问 `http://127.0.0.1:8000` 即可使用 Web 界面：

- 点击 **Start Stream** 开始实时转写
- 点击 **Upload File** 上传音频文件处理

### API 接口

#### WebSocket 实时流

```
ws://127.0.0.1:8000/ws/v1/stream/{client_id}
```

**输入**: PCM Int16 字节流 (16kHz)

**输出**:
```json
{
  "speaker": "Spk_1234",
  "text": "增量文本",
  "time": "14:30:25"
}
```

#### 文件上传

```bash
curl -X POST "http://127.0.0.1:8000/v1/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@audio.wav"
```

**响应**:
```json
{
  "status": "success",
  "filename": "audio.wav",
  "speaker": "Spk_1234",
  "text": "完整的转写文本"
}
```

#### 获取模型信息

```bash
curl http://127.0.0.1:8000/v1/models
```

<details>
<summary>🔧 更多配置选项</summary>

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| host | 0.0.0.0 | HOST | 监听地址 |
| port | 8000 | PORT | 监听端口 |
| speaker_engine | campplus | SPEAKER_ENGINE | 声纹引擎类型 |
| buffer_threshold | 32000 | - | 音频缓冲阈值（采样点） |
| silence_threshold | 0.008 | - | 静音检测阈值 |
| timeout | 30s | - | 无音频超时断开 |

</details>

## 🏗️ 项目结构

```
matrix-live-diarizer/
├── main.py                     # 应用入口
├── app/                        # FastAPI 应用层
│   ├── api/
│   │   ├── websocket.py        # WebSocket 实时流接口
│   │   └── upload.py           # 文件上传接口
│   ├── services/
│   │   └── session.py          # 会话上下文管理
│   ├── config.py               # 配置管理
│   └── constants.py            # 常量定义
├── engine/                     # 推理引擎层
│   ├── asr_engine.py           # ASR 引擎 (Qwen3-ASR)
│   └── speaker/                # 声纹引擎模块
│       ├── speaker_factory.py  # 引擎工厂
│       ├── campplus_engine.py  # CamPlus 引擎
│       ├── eres2net_engine.py  # ERes2NetV2 引擎
│       └── wespeaker_engine.py # Wespeaker 引擎
└── web/
    └── index.html              # Web 前端界面
```

## 🎯 声纹引擎对比

| 引擎 | EER (VoxCeleb) | EER (CNCeleb) | 参数量 | 速度 | 适用场景 |
|:----:|:--------------:|:-------------:|:------:|:----:|:--------:|
| **CamPlus** | 0.65% | 6.78% | 7.2M | ⚡ 快 | 实时场景 (默认) |
| **ERes2NetV2** | 0.61% | 6.14% | 17.8M | 🚗 中 | 高精度需求 |
| **Wespeaker** | 1.05% | 6.92% | 6.34M | ⚡ 快 | 经典稳定 |

## 🧠 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  WebSocket  │  │  REST API   │  │    Web Interface    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼───────────────────┼──────────────┘
          │                │                   │
          ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  Session Manager                       │   │
│  │         (Audio Buffer / Incremental Text)             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Engine Layer                           │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │     ASR Engine      │    │      Speaker Engine         │ │
│  │   (Qwen3-ASR)       │    │  ┌─────┬─────┬─────────┐   │ │
│  │  - VAD Detection    │    │  │Camp+│ERes2│Wespeaker│   │ │
│  │  - Preprocessing    │    │  └─────┴─────┴─────────┘   │ │
│  │  - Hallucination    │    │  - ChromaDB Storage        │ │
│  └─────────────────────┘    │  - Incremental Learning    │ │
│                              └─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 📦 模型来源

| 模块 | 模型 | 来源 |
|------|------|------|
| ASR | [Qwen3-ASR-0.6B](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B) | ModelScope |
| Speaker | [CamPlus](https://modelscope.cn/models/damo/speech_campplus_sv_zh-cn_16k-common) | ModelScope |
| Speaker | [ERes2NetV2](https://modelscope.cn/models/iic/speech_eres2netv2_sv_zh-cn_16k-common) | ModelScope |
| Speaker | [Wespeaker](https://modelscope.cn/models/iic/speech_resnet34_sv_zh-cn_3dspeaker_16k) | ModelScope |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | torch.hub |

## ⚠️ 注意事项

- **单进程运行**: Mac MPS 需单进程，避免内存溢出
- **采样率**: 音频输入必须是 16kHz
- **首次启动**: 模型会自动下载到本地缓存，请确保网络畅通

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

## 📄 License

本项目基于 [MIT License](LICENSE) 开源。

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐ Star 支持一下！**

</div>