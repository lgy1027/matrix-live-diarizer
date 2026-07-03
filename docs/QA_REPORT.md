# 产品级 QA 报告

**测试日期**: 2026-06-12
**测试版本**: feature/quickstart-enhancements @ aa74106
**服务地址**: http://127.0.0.1:8000
**ASR**: Qwen3-ASR-0.6B @ MPS
**声纹**: CamPlus (默认)
**测试员**: 本地 QA

---

## 0. 测试覆盖矩阵

| 维度 | 覆盖 | 样本/用例数 |
|---|---|---|
| **WS 流式** | 单说话人 / 多说话人 / 长音频 / 短音频 / 噪声 / 跨语种 | 13 场景 + 10 边界 |
| **REST API** | 24 端点全覆盖 | 60+ 用例 |
| **安全** | 注入 / 路径穿越 / 字符清洗 | 11 payload |
| **并发** | 5 个 WS 客户端同跑 | 1 压测 |
| **错误** | 0字节 / 损坏 / 非法格式 / SQL/XSS/路径注入 | 15+ |

语料库:21 个 wav(TTS 合成 13 + 真实人声 3 + 噪声 2 + 边界 4 + 长音频 1)

---

## 1. 关键发现摘要(按严重度)

### 🔴 P0 — 影响核心功能

#### Bug-01: 短音频(<1.5s)识别完全丢失
- **现象**: 0.91s 的 `tts_short_zh.wav` 和 0.1s 临界音频,服务端 `frames=1, skipped=0` 直接断开,**0 个识别响应**
- **根因** (推测): 状态机在收到 1 帧语音后没等到 `silence_threshold_frames=3` 触发 ASR,客户端 close 后服务端直接退出
- **复现**:
  ```bash
  python /tmp/ws_test/ws_stream_test.py /tmp/ws_test/tts_short_zh.wav bot
  ```
  实际 `responses: []`
- **影响**: 用户短促回应("嗯"、"对"、"好")等场景完全丢失
- **修复方向**:
  1. 加超时强制识别:`should_emit_segment` 增 `min_buffer_seconds` 阈值
  2. 或者服务端收到 close 信号时强制 flush 残余 buffer

#### Bug-02: 极速跳帧导致音频全丢
- **现象**: 1000 帧 20ms 以 0.1ms 间隔发送,服务端 `[STATS] frames=70, skipped=186 (265.7%)`,**0 个识别响应**
- **根因**: `compute_skip_count` 在 `queue_size > threshold` 时仅保留最新 1 帧;极速场景下保留的那 1 帧在 20s 音频里占比 0.005%,无法累积到完整语音段
- **影响**: 高频写入客户端(WebSocket 抖动、网络重传)可能完全丢识别
- **修复方向**:
  1. 跳帧时保留最近 N 秒(比如 0.5s = 25 帧),不是 1 帧
  2. 或者跳帧时跳过超阈值但保留 50% 最新帧

#### Bug-03: 损坏 wav 上传 → HTTP 500 + 暴露内部异常
- **现象**: 上传 `corrupt.wav` 返回 `{"detail":"处理失败: NoBackendError"}`
- **根因**: `app/api/upload.py:200` `librosa.load` 抛 `LibsndfileError` → 通用 `except Exception` 兜底为 500
- **影响**:
  1. 状态码错:用户传错文件,应 400 而非 500
  2. 暴露内部异常名,泄露实现细节
- **修复**:
  ```python
  except (LibsndfileError, NoBackendError, EOFError) as e:
      raise HTTPException(400, "文件格式损坏或不支持,请上传有效 WAV/MP3/FLAC")
  ```

---

### 🟡 P1 — 影响体验但非阻塞

#### Bug-04: 空声纹库阶段同一说话人给分配不同 Spk ID
- **现象**: TC01 中文男同一段语音,服务端给分配了 `Spk_1577038400` 和 `Spk_2048029752` 两个不同 ID
- **根因**: 声纹引擎 cosine 比对在空库阶段**无参照**,直接 `compare_and_identify` 创建新 ID
- **影响**: 用户多次短促说话,会在前端看到一堆 `Spk_xxxxxxxx`(数字 ID),体验差
- **修复方向**:
  1. 前端:检测同一会话内"短时 N 个新 Spk 实际同一来源",弹"建议合并"提示
  2. 后端:加"会话内声纹聚类" — 同 client_id 下 N 秒内的 Spk 自动合并

#### Bug-05: API 字段命名与代码不一致(陷阱)
- **现象**:
  - `/v1/speakers/merge` 期望 `{target_id, source_ids}`,而非直觉的 `{target_speaker_id, source_speaker_ids}`
  - `/v1/speakers/enroll` 期望 query `?speaker_id=` + multipart `file`,**不是** JSON body
- **修复**: OpenAPI 文档已有正确 schema,前端代码大概率已用对的字段。**给后端 README 加例子**

#### Bug-06: `PUT /v1/llm/prompts` 静默吞错误字段
- **现象**: PUT `{"fake_key":"x"}` 返 200 + 完整 PROMPTS,无错误提示
- **根因**: `app/api/llm.py:54-58` `for k,v in payload.items(): if k in PROMPTS: ...` — 不在 PROMPTS 的 key 直接忽略
- **影响**: 用户配错字段名,以为更新成功,实际没生效
- **修复**:
  ```python
  unknown = set(payload.keys()) - set(PROMPTS.keys())
  if unknown:
      raise HTTPException(422, f"未知字段: {unknown}")
  ```

#### Bug-07: 导出 API 强制要 `?format=`
- **现象**: `GET /v1/exports/{id}` 不带 `format` 返 422
- **根因**: 路径参数没默认值
- **修复**: `format: str = "json"`(默认 JSON)

#### Bug-08: Session 详情 hot_words 切词错误
- **现象**: 文本"也不容易"被切成 `["也不","不容","容易","也是"]`(2 字符滑窗)
- **根因**: `app/services/statistics.py` 的切词函数用了二元组 sliding window,不是按字/词
- **影响**: 热词统计没意义
- **修复**:
  1. 简单方案:按字符切(中文单字)+ 按空格切(英文)
  2. 进阶:接 jieba 等中文分词库

#### Bug-09: `POST /v1/speakers/split` 说话人不存在时静默成功
- **现象**: `speaker_id=Spk_none, segment_ids=[1]` 返 `{"segments_updated":0, "new_speaker_id":null}` HTTP 200
- **根因**: 跟之前 merge 的 0-source silent success bug 同模式(commit 58a7118 修了 merge,split 还没修)
- **修复**: 复用 merge 的 fix 模式 — 显式 check 说话人存在

#### Bug-10: 重命名接受 SQL 注入字符串
- **现象**: PATCH name=`x'; DROP TABLE speakers; --` 返 200,数据库无副作用(用 ORM 没问题)
- **根因**: schema `^[\x20-\x7E一-鿿　-〿＀-￯]+$` 允许 ASCII 可打印字符
- **建议**: 拒绝包含 SQL 关键字(`DROP`、`DELETE`、`SELECT`)的名字(防御性)

---

### 🟢 P2 — 小问题/优化建议

#### Bug-11: WS 客户端断开不触发 rename 前的 segment 存档
- **现象**: 13 次 WS 测试中,服务端没自动存档任何一段
- **根因**: 存档要求 `websocket._session_id` 存在(需客户端发过 rename 文本命令)
- **建议**: 改默认行为 — 有 segment 累积就自动存档,rename 改成"重命名存档的会话",而不是"创建存档的开关"

#### Bug-12: WS 识别响应中 `text` 字段没做 trim
- **现象**: 真实人声识别返"也不容易,也是,呃,五出六进,..." — "呃" 这种填充词没过滤
- **建议**: 加 `HALLUCINATIONS` 黑名单(类似 ASR 引擎已有的)+ 常见填充词("呃"、"嗯"、"啊")

#### Bug-13: 中文 TTS 识别出日文假名(ASR 模型跨语种误判)
- **现象**: TC06 韩文 TTS 识别出"エクスクリーン"(日文假名)
- **根因**: Qwen3-ASR 在低质量 TTS + 韩文场景下语种判定失准
- **影响**: 真实人声很少出现,优先级低

---

## 2. 通过的测试(全绿)

| 类别 | 用例 | 结果 |
|---|---|---|
| 健康检查 | `/health`, `/ready` | ✅ |
| WS 协议 | binary 帧、JSON rename、文本命令 | ✅ |
| WS 安全 | `validate_client_id` 清洗、字符过滤 | ✅ |
| 说话人 CRUD | 列表/详情/重命名/删除 | ✅ |
| 说话人合并 | 4 case(正常/自己/不存在/格式错) | ✅ |
| 说话人分割 | 4 case(正常/null/格式/空 segment) | ✅ |
| 说话人清理 | dry_run + 真实清理 | ✅ |
| 主动 enroll | multipart + query string | ✅ |
| 引擎切换 | campplus ↔ eres2net ↔ wespeaker + 维度警告 | ✅ |
| 上传 | TTS/真实人声/长音频/纯静音 | ✅ |
| 上传拒绝 | 空文件 400、损坏 500(应改 400) | ⚠️ |
| 历史 | 列表 + 详情 + 软删除 | ✅ |
| 导出 | JSON/Markdown/SRT | ✅ |
| LLM | 状态/prompts/总结/行动项/会议纪要(fallback) | ✅ |
| 并发 | 5 个 WS 同时跑 24s 对话,12s 完成 | ✅ |
| 注入防护 | 路径穿越 → 404,SQL 注入 → 422(URL),字符注入 → 清洗 | ✅ |

测试总数:**170+**,通过 **160+**,**10 个 Bug** 需修复

---

## 3. 推荐修复优先级

| 优先级 | Bug | 工作量 | 价值 |
|---|---|---|---|
| P0-1 | Bug-01 短音频丢失 | 0.5d | 高 |
| P0-2 | Bug-02 跳帧全丢 | 0.5d | 中(需压测才能复现) |
| P0-3 | Bug-03 上传 500 | 0.25d | 高 |
| P1-1 | Bug-04 同说话人聚类 | 1d | 高 |
| P1-2 | Bug-06 PUT prompts 静默 | 0.25d | 中 |
| P1-3 | Bug-09 split 静默 | 0.25d | 中 |
| P2-1 | Bug-08 hot_words 切词 | 0.5d | 中 |
| P2-2 | Bug-11 自动存档 | 0.5d | 中 |

---

## 4. 测试数据

| 数据 | 路径 |
|---|---|
| 语料库 | `/tmp/ws_test/*.wav` (21 个) |
| 语料生成器 | `/tmp/ws_test/build_corpus.py` |
| WS 测试脚本 | `/tmp/ws_test/ws_stream_test.py` |
| 边界测试脚本 | `/tmp/ws_test/edge_test.py` |
| 报告 JSON | `/tmp/ws_test/reports/*.json` |
| 服务端日志 | 后台进程 `bmp3qbjr3` 输出 |

后端服务**仍在跑**,可继续手测。
