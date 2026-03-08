# Matrix Live Diarizer

实时语音转写与说话人识别系统，基于 Qwen3-ASR 构建。

## 特性

- **实时转写**：WebSocket 流式传输，说话即转写
- **说话人识别**：自动区分不同说话人
- **多引擎支持**：CamPlus / ERes2NetV2 / Wespeaker 三种声纹引擎
- **离线处理**：支持上传音频文件批量处理

## 快速开始

### 安装依赖

```bash
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

服务启动后访问 http://127.0.0.1:8000

## API 接口

### WebSocket 实时流

```
ws://127.0.0.1:8000/ws/v1/stream/{client_id}
```

- 输入：PCM Int16 字节流（16kHz）
- 输出：`{"speaker": "Spk_xxx", "text": "增量文本", "time": "HH:MM:SS"}`

### 文件上传

```
POST /v1/upload
Content-Type: multipart/form-data
```

### 模型信息

```
GET /v1/models
```

## 项目结构

```
matrix-live-diarizer/
├── main.py                 # 入口
├── app/
│   ├── api/
│   │   ├── websocket.py    # WebSocket 接口
│   │   └── upload.py       # 文件上传接口
│   ├── services/
│   │   └── session.py      # 会话管理
│   ├── config.py           # 配置
│   └── constants.py        # 常量
├── engine/
│   ├── asr_engine.py       # ASR 引擎 (Qwen3-ASR)
│   └── speaker/
│       ├── campplus_engine.py    # CamPlus 声纹引擎
│       ├── eres2net_engine.py    # ERes2NetV2 引擎
│       └── wespeaker_engine.py   # Wespeaker 引擎
└── web/
    └── index.html          # Web 界面
```

## 配置参数

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| host | 0.0.0.0 | HOST | 监听地址 |
| port | 8000 | PORT | 监听端口 |
| speaker_engine | campplus | SPEAKER_ENGINE | 声纹引擎类型 |
| buffer_threshold | 32000 | - | 音频缓冲阈值（采样点） |
| silence_threshold | 0.012 | - | 静音检测阈值 |
| timeout | 30s | - | 无音频超时断开 |

## 声纹引擎对比

| 引擎 | EER (VoxCeleb) | EER (CNCeleb) | 参数量 | 速度 | 适用场景 |
|------|----------------|---------------|--------|------|----------|
| CamPlus | 0.65% | 6.78% | 7.2M | 快 | 实时场景 |
| ERes2NetV2 | 0.61% | 6.14% | 17.8M | 中 | 高精度需求 |
| Wespeaker | 1.05% | 6.92% | 6.34M | 快 | 经典稳定 |

## 模型来源

| 模块 | 模型 | 来源 |
|------|------|------|
| ASR | Qwen3-ASR-0.6B | ModelScope |
| 声纹 | CamPlus / ERes2NetV2 / Wespeaker | ModelScope |

## 注意事项

1. **单进程运行**：Mac MPS 需单进程，避免内存溢出
2. **采样率**：音频输入必须是 16kHz
3. **幻觉词**：系统会自动过滤常见幻觉输出

## License

MIT
