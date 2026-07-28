# API

beta 阶段的 API 面向单个本地用户。稳定版发布前契约仍可能变动。除健康检查、模型目录、登录和有限的状态端点外，本地绕过关闭时 `/v1/*` 均需鉴权。

## 会议

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/v1/meetings/upload?mode=quick|meeting` | 校验并排队一段音频录音 |
| `GET` | `/v1/meetings` | 会议列表 |
| `GET` | `/v1/meetings/search?q=...` | 按转写文本搜索 |
| `GET/PATCH/DELETE` | `/v1/meetings/{id}` | 读取、重命名或删除会议 |
| `GET` | `/v1/meetings/{id}/audio` | 流式播放受管音频 |
| `PATCH` | `/v1/meetings/{id}/segments/{segment_id}` | 校正文本 |
| `PATCH` | `/v1/meetings/{id}/segments/speaker` | 批量指派所选段 |
| `PATCH` | `/v1/meetings/{id}/speakers/{speaker_id}/person` | 确认或清除人物 |
| `POST/PUT` | `/v1/meetings/{id}/notes/{summary|minutes|actions}` | 生成或编辑纪要 |
| `GET` | `/v1/meetings/{id}/export?format=markdown|srt|vtt|json` | 导出 |

`status=ready` 表示转写可用。`transcript_state=draft|refined` 区分临时实时转写与完成的 refinement。`diarization_status` 单独查看：`completed`、`unavailable`、`pending` 或 `not_requested`。refinement 失败时仍保留可用的 draft。
`status=processing` 期间，draft 文本、说话人/人物指派和会议输出为只读，以防原子化的 refinement 覆盖用户改动。会议详情含最近一次 `processing_job`，用于阶段/进度 UI。

会议详情可能含 `processing_manifest`，描述该次处理的不可变溯源。对引入 manifest 之前创建的记录，客户端须将其嵌套字段视为可选：

```json
{
  "version": 1,
  "strategy": "external-diarization",
  "asr": {"engine": "qwen3", "model": "Qwen/Qwen3-ASR-0.6B", "timestamp_granularity": "word"},
  "diarization": {"provider": "pyannote", "status": "completed", "alignment": "word-timestamps"},
  "speaker_identity": {"engine": "campplus", "model_id": "modelscope:..."},
  "generated_at": "2026-07-16T10:00:00Z"
}
```

`SPEAKER_00`、`SPEAKER_01` 等标签是限定于单场会议的匿名标识，不是人物 ID。`identity_status` 取值为 `anonymous`、`suggested`、`auto_matched` 或 `confirmed`。严格匹配可在带溯源的情况下自动展示并导出；建议在通过 speaker/person `PATCH` 确认前，转写中保持匿名。

## 任务与人物

- `GET /v1/jobs`, `GET /v1/jobs/{id}`
- `POST /v1/jobs/{id}/cancel`, `POST /v1/jobs/{id}/retry`
- `GET/POST /v1/people`
- `GET/PATCH/DELETE /v1/people/{id}`
- `POST /v1/people/{id}/samples`
- `GET /v1/people/{id}/samples/{sample_id}/audio`
- `DELETE /v1/people/{id}/samples/{sample_id}`

人物是本地注册的身份。自动展示需要：兼容的 embedding 模型、会议中足够的语音、至少两个强注册样本，以及比普通建议更严格的置信度/歧义阈值。

## 运行时配置

- `GET /v1/models`, `GET /v1/engines`, `PUT /v1/engine`
- `GET /v1/asr/engines`, `PUT /v1/asr/engine`
- `GET/PUT /v1/llm/settings`, `GET /v1/llm/status`, `POST /v1/llm/test`
- `POST /v1/auth/login`, `GET /v1/auth/me`, `POST /v1/auth/change-password`
- `GET /health`, `GET /ready`
- `WS /ws/v1/stream/{client_id}`

服务运行时 OpenAPI 见 `/docs`。

`GET /v1/llm/status` 是被动接口，只返回配置和最近一次显式测试结果。只有 `POST /v1/llm/test` 会向配置的 OpenAI 兼容 `/chat/completions` endpoint 发送一次最小 `ping` 请求。保存 LLM 设置会清除上次测试结果，但不连接 LLM 服务。

LLM API key 从 `LLM_API_KEY` 进程环境读取。不接受设置 API 提交、不返回给浏览器、不存入 SQLite。
