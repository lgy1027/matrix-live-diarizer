# API 接口参考

所有 API 均以 `http://127.0.0.1:8000` 为基址（可改 `.env` 的 `PORT`）。

> ⚠️ **速率限制**：默认 60/分钟、1000/小时。生产环境放 nginx 后需配
> `trusted_proxies`（`app/middleware/rate_limit.py`），否则客户端伪造
> `X-Forwarded-For` 即可绕过。

---

## 1. WebSocket 实时流

```
ws://127.0.0.1:8000/ws/v1/stream/{client_id}
```

**输入**：PCM Int16 字节流（16kHz 单声道）
**client_id**：`[a-zA-Z0-9_]{1,64}`（防日志注入）

**服务端推送**（JSON）：
```json
{
  "speaker": "Spk_1234",
  "text": "增量文本",
  "time": "14:30:25"
}
```

**客户端命令**（JSON）：
```json
{ "action": "rename", "title": "新会话名" }
```

## 2. 文件上传

```bash
curl -X POST "http://127.0.0.1:8000/v1/upload?enable_diarization=true" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@audio.wav"
```

**参数**：
- `enable_diarization` (bool, default `true`) — 是否启用说话人识别
- `file` — 音频文件（500MB 上限，1 小时时长上限）

**支持格式**：`.wav .mp3 .m4a .flac .ogg .aac .wma`

**响应**：
```json
{
  "status": "success",
  "filename": "audio.wav",
  "speaker": "Spk_001",
  "text": "完整转写",
  "duration": 12.5,
  "speakers": ["Spk_001", "Spk_002"],
  "segments": [
    {"speaker": "Spk_001", "text": "你好", "start_time": 0.0, "end_time": 1.5}
  ],
  "session_id": "uuid-xxx"
}
```

> 实现细节：`app/api/upload.py:115,209` 文件上传路径用 `use_buffer=False`
> 跳过声纹 buffer（防同文件识别为不同声纹的污染）。

## 3. 说话人管理

### 获取列表

```bash
# 全部说话人
curl http://127.0.0.1:8000/v1/speakers

# 按 session 过滤
curl "http://127.0.0.1:8000/v1/speakers?session_id=session_a"
```

### 获取单个

```bash
curl http://127.0.0.1:8000/v1/speakers/Spk_001
```

### 重命名

```bash
curl -X PATCH http://127.0.0.1:8000/v1/speakers/Spk_001 \
  -H "Content-Type: application/json" \
  -d '{"name": "张三"}'
```

### 删除单个

```bash
curl -X DELETE http://127.0.0.1:8000/v1/speakers/Spk_001
```

### 批量清理（高级）

```bash
curl -X POST http://127.0.0.1:8000/v1/speakers/cleanup \
  -H "Content-Type: application/json" \
  -d '{
    "speaker_ids": ["Spk_001", "Spk_002"],
    "max_count": 5,
    "dry_run": false,
    "cascade": true
  }'
```

**参数说明**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `speaker_ids` | string[] | `null` | 显式指定要删的 ID 列表（优先级最高）|
| `session_id` | string | `null` | 只清理该 session 下的声纹 |
| `max_count` | int | `5` | 删 `sample_count <= max_count` 的低质量声纹 |
| `dry_run` | bool | `true` | `true` 时只返回候选，不会真删 |
| `cascade` | bool | `false` | `true` 时先清空 `segments.speaker_id` 引用（避免孤立）|

**响应**：
```json
{
  "dry_run": false,
  "candidates": ["Spk_001", "Spk_002"],
  "deleted": ["Spk_001", "Spk_002"],
  "total_before": 12,
  "total_after": 10,
  "cascade_segments_cleared": 23
}
```

**三种过滤模式**（优先级从高到低）：
1. **`speaker_ids` 显式指定** — Voice Library 批量选择用这个
2. **`session_id` + `max_count`** — 删某 session 下低质量样本
3. **仅 `max_count`** — 删所有 session 中的低质量样本

## 4. 引擎管理

### 获取所有引擎信息

```bash
curl http://127.0.0.1:8000/v1/engines
```

### 运行时切换引擎

```bash
curl -X PUT http://127.0.0.1:8000/v1/engine \
  -H "Content-Type: application/json" \
  -d '{"engine_type": "eres2net"}'
```

> 切换后 `embedding_dim` 不同时会返回 `warning`，已存声纹向量不兼容，
> 需重新注册。详见 `engine/speaker/speaker_factory.py:139-162`。

### 获取 ASR 模型信息

```bash
curl http://127.0.0.1:8000/v1/models
```

## 5. 健康检查

```bash
# 存活检查（进程在跑就 200）
curl http://127.0.0.1:8000/health

# 就绪检查（ASR + Speaker 都加载完才 200）
curl http://127.0.0.1:8000/ready
```

**响应**：
```json
{ "status": "ready", "asr": true, "speaker": true, "timestamp": 1780807843.5 }
```

## 6. LLM 端点（可选）

仅在 `LLM_ENABLED=true` 时可用。详见 [`docs/LLM_SETUP.md`](LLM_SETUP.md)。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/llm/status` | GET | LLM 启用状态 + 可用性 |
| `/v1/llm/summarize` | POST | 生成会话摘要（`session_id`, `max_words`）|
| `/v1/llm/action-items` | POST | 提取行动项 |
| `/v1/llm/minutes` | POST | 生成会议纪要 |
| `/v1/llm/prompts` | GET / PUT | prompt 模板（**PUT 限本机访问**）|

## 7. 历史与导出（v0.2+）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/history` | GET | 转写历史列表（分页 + 搜索）|
| `/v1/sessions/{id}` | GET | 会话详情 |
| `/v1/exports/{id}?format=srt\|vtt\|md\|json` | GET | 4 种格式导出 |
| `/v1/search?q=...&session_id=...&speaker_id=...&limit=50` | GET | 全文搜索（v0.4+,Roadmap #2.2）|

### `/v1/search` 全文搜索（v0.4+）

搜所有 segment.text 内的关键词,返回带高亮 snippet 的命中列表。

**Query 参数**:
- `q` (必填,1-200 字符):搜索关键词
- `session_id` (可选):限定会话
- `speaker_id` (可选):限定说话人
- `limit` (可选,默认 50,1-200):返回数量

**响应**:
```json
{
  "query": "今天我们",
  "total": 5,
  "session_id": null,
  "speaker_id": null,
  "hits": [
    {
      "segment_id": 42,
      "session_id": "abc-123",
      "session_title": "周会-1",
      "session_filename": "weekly.wav",
      "speaker_id": "Spk_001",
      "text": "今天我们讨论语音识别...",
      "snippet": "今天[match]我们[/match]讨论语音识别",
      "start_time": 0.0,
      "end_time": 5.2,
      "jump_url": "/web/detail.html?id=abc-123&seg=42"
    }
  ]
}
```

**中文支持**:FTS5 trigram 分词。3+ 字命中率高,2 字走 LIKE 兜底(2 字中文 substring 也能搜)。

**示例**:
```bash
curl 'http://127.0.0.1:8000/v1/search?q=今天我们'
curl 'http://127.0.0.1:8000/v1/search?q=语音识别&session_id=abc-123'
curl 'http://127.0.0.1:8000/v1/search?q=OpenAI&limit=20'
```

## 8. 环境变量参考

### 服务器

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| host | `0.0.0.0` | `HOST` | 监听地址 |
| port | `8000` | `PORT` | 监听端口 |
| workers | `1` | `WORKERS` | 工作进程数（MPS 必须 1）|
| debug | `false` | `DEBUG` | 调试模式 |

### 音频处理

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| sample_rate | `16000` | `AUDIO_SAMPLE_RATE` | 采样率 |
| buffer_threshold | `32000` | `AUDIO_BUFFER_THRESHOLD` | 缓冲阈值（采样点）|
| silence_threshold | `0.008` | `AUDIO_SILENCE_THRESHOLD` | 静音阈值 |
| timeout_seconds | `30.0` | `AUDIO_TIMEOUT_SECONDS` | 无音频超时断开 |
| max_buffer_seconds | `10` | `AUDIO_MAX_BUFFER_SECONDS` | 缓冲区上限（秒）|
| max_segment_seconds | `5` | `AUDIO_MAX_SEGMENT_SECONDS` | 单语音段最大长度 |

### VAD

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| vad_threshold | `0.5` | `VAD_THRESHOLD` | VAD 灵敏度 |
| min_speech_duration_ms | `200` | `VAD_MIN_SPEECH_DURATION` | 最小语音时长 |

### 速率限制

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| rate_limit_enabled | `true` | `RATE_LIMIT_ENABLED` | 是否启用 |
| requests_per_minute | `60` | `RATE_LIMIT_REQUESTS_PER_MINUTE` | 每分钟上限 |
| requests_per_hour | `1000` | `RATE_LIMIT_REQUESTS_PER_HOUR` | 每小时上限 |

### 声纹引擎

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| speaker_engine | `campplus` | `SPEAKER_ENGINE` | 启动时默认引擎 |
| asr_device | `auto` | `ASR_DEVICE` | auto / cpu / mps / cuda |
| asr_load_timeout_sec | `90` | `ASR_LOAD_TIMEOUT_SEC` | 模型加载超时（防 MPS 死锁）|

### 存储

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| history_enabled | `true` | `STORAGE_HISTORY_ENABLED` | 是否自动存档会话 |
| db_path | `./data/matrix.db` | `STORAGE_DB_PATH` | SQLite 路径 |

### LLM

详见 [`docs/LLM_SETUP.md`](LLM_SETUP.md)。
