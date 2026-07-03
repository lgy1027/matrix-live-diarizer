# 模型选型参考

本项目以"小、快、可在消费级硬件跑"为原则做模型选型。本文档归档已调研过的候选模型,以及它们的取舍。

---

## 当前可用

### ASR: Qwen3-ASR-0.6B（默认）
- **来源**: ModelScope `Qwen/Qwen3-ASR-0.6B`
- **大小**: 1.8GB
- **设备**: MPS / CUDA / CPU(默认 auto,mps 优先,90s 超时回退)
- **能力**: 多语种(中英日韩等)、50+ 语言识别、自动语言检测、长音频(分段)
- **可选**: Qwen3-ForcedAligner-0.6B(600MB),给字级时间戳用,`ASR_WORD_TIMESTAMPS=true` 启用
  - **开启后效果**:
    - WebSocket 响应 / upload 响应 / SQLite 存档的 segments 都会带 `words: [{text, start, end}]`
    - SRT/VTT 字幕按字切分(0.3s/字 vs 默认 3s/段),适合视频剪辑/卡拉 OK
    - 前端 detail.html / index.html hover 字幕显示该字时间
  - **代价**:
    - 首次启动多下载 600MB 模型(国内需 HF 镜像)
    - ASR 加载多 5-10s(MPS 上偶发死锁,90s 超时回退 CPU)
    - 每次推理多 50-200ms(对齐计算)
  - **推荐**: 个人学习保持 false(轻量);需要精确字幕/视频剪辑场景开 true
- **优点**: 中文识别极强,SOTA 表现,社区活跃
- **缺点**: 体积较大,低端机器加载慢;HF 镜像依赖

### 声纹: CamPlus / ERes2NetV2 / ResNet34 (Wespeaker)
- **来源**: ModelScope `damo/speech_campplus_sv_zh-cn_16k-common` 等
- **大小**: 7-18M 参数(都 < 100MB)
- **能力**: 说话人识别(谁在说话)、声纹库累积、cosine 距离比对
- **切换**: `SPEAKER_ENGINE=campplus|eres2net|wespeaker` 运行时可切
- **embedding_dim**: CamPlus/ERes2Net=192,Wespeaker=256(切引擎不兼容老数据)

### ASR: SenseVoice / Paraformer / Paraformer Streaming
- **来源**: ModelScope / FunASR
- **依赖**: `funasr>=1.2.0`
- **切换**: 设置页或 `PUT /v1/asr/engine`
- **行为**: 新 ASR 下载/加载完成前继续使用旧 ASR;加载失败不会影响当前引擎
- **适用**:
  - SenseVoice-Small: 多语种上传转写,模型更轻
  - Paraformer: 中文会议/访谈离线转写
  - Paraformer Streaming: 低延迟实时字幕

### VAD: Silero VAD
- **来源**: torch.hub `snakers4/silero-vad`
- **大小**: < 2MB
- **设备**: CPU(很小,不值得放 GPU)
- **作用**: 流式状态机 SILENCE ↔ SPEECH 切换,触发 ASR

---

## 调研过但未采用

### SenseVoice-Small 评估记录
- **大小**: ~250MB(对比 Qwen3-ASR-0.6B 的 1.8GB)
- **来源**: ModelScope `iic/SenseVoiceSmall`
- **能力**: ASR + 语种识别 + 情感识别 + 声音事件检测(AED),多任务
- **优点**: 体积小 7x,速度快(实测 ~2x),多语种 50+
- **缺点**:
  - **不支持流式**:SenseVoice 是非自回归,完整段输入才能识别(WebSocket 实时场景不适用)
  - **中文方言仅普通话 + 粤语**:`labels` 字段 50+ 语言是指"语种",不是"方言"。粤语/闽南语/上海话等不支持
  - **中文表现弱于 Qwen3-ASR-0.6B**:在小规模对比测试中,Qwen3-ASR 在普通话 / 英文上的 WER 低 2-3%
  - **声学事件 + 情感不是本项目目标**:多任务反而拖慢主任务
- **结论**: 已作为可选 ASR 集成,适合"批量处理短音频 + 多语种"场景;默认仍保留 Qwen3-ASR。

### ZipEnhancer (speech_zipenhancer_ans_multiloss_16k_base)
- **大小**: 2.04M 参数(约 8MB,极小)
- **来源**: ModelScope `iic/speech_zipenhancer_ans_multiloss_16k_base`
- **能力**: **单通道语音降噪 / 增强** — 16kHz 噪声音频 → 16kHz 干净人声
- **论文**: ICASSP 2025 [arxiv:2501.05183](https://arxiv.org/abs/2501.05183)
- **基准**: DNS Challenge 2020 上 PESQ 3.69(SOTA 同规模)
- **优点**:
  - 极小(2M 参数)、SOTA 降噪质量
  - 16kHz in/out,与本项目采样率匹配
  - CPU/MPS 都能跑
- **缺点 / 风险**:
  - **不是 ASR,不是声纹** — 是前端信号处理
  - **职责冲突**: 插进来变成 `VAD → ZipEnhancer → ASR → Speaker` 四级流水线,违反"单进程"原则
  - **过增强失真**: 干净语音可能被当作噪声削掉
  - **声纹退化**: CamPlus 训练在 clean 上,降噪会破坏说话人特征,反而降低 EER
  - **延迟代价**: 2-3s 一段推理 50-100ms(CPU/MPS),实时流必须串行
- **结论**: 暂不集成。如果未来要做"嘈杂环境优化":
  1. 先在真实噪声样本上做 A/B 测试,看 ASR/CamPlus 在 SNR 5/10/15dB 下的退化曲线
  2. 默认关闭,`.env` 加 `NOISE_ENHANCEMENT=zipenhancer`
  3. 声纹提取强制走**原始**音频(跳过降噪)
  4. 加 PESQ 量化指标,让用户看降噪前后质量差

### 其他小 ASR 候选
- **Paraformer-small / Paraformer Streaming** (FunASR): 已作为可选 ASR 集成。
- **Whisper-tiny**: 75MB,英文强,中文弱,延迟高。不推荐。
- **Whisper-base**: 150MB,中文一般,延迟高。不推荐。
- **WenetSpeech** 系列: 工业级,通常 1GB+,与本项目"小"原则不符。

---

## 选型原则

1. **< 2GB 模型优先**: 1.8GB 的 Qwen3-ASR-0.6B 是上限(MPS 容易 OOM)
2. **中文为第一优先级**: 项目主要服务中文场景(README/i18n 都是简体中文)
3. **流式友好**: WebSocket 实时流优先选择低延迟模型;离线上传可使用非流式模型
4. **可热切换**: ASR 与声纹引擎均支持运行时切换
5. **离线 / 国产化**: ModelScope 镜像 + 阿里生态(Qwen/CamPlus/ERes2Net)优先

---

## 升级路径(v0.4+ 候选)

| 维度 | 当前 | 候选 | 收益 | 代价 |
|---|---|---|---|---|
| ASR | Qwen3-ASR-0.6B | Paraformer-streaming | 流式延迟 ↓50% | 中文 WER 略升 |
| ASR | Qwen3-ASR-0.6B | Qwen3-ASR-1.7B | WER ↓2-3% | 模型 3GB+,MPS 易 OOM |
| 声纹 | CamPlus | ERes2NetV2 (默认) | CN-Celeb EER 6.14% (vs 6.78%) | 慢一些(17M vs 7M 参数) |
| 降噪 | 无 | ZipEnhancer | 嘈杂环境 +5% WER | 加 50ms 延迟,有声纹退化风险 |
| 对齐 | 无(可选 Qwen3-ForcedAligner) | 直接用 Qwen3-ASR 自身的 timestamp | 简化流程 | Qwen3-ASR 原生时间戳不够准 |

新模型评估前,先看它是否解决了**已验证的真实问题**,而不是"看着更好"。
