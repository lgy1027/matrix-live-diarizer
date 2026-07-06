# Matrix Live Diarizer 路线图

> 状态：持续更新
> 维护者：lgy1027

本文件汇总项目计划增强和新增的功能点，按优先级分 4 档。每条关注：

- **做什么**
- **为什么（用户痛点 / 商业价值）**
- **怎么落地（关键实现路径）**
- **影响面（涉及哪些模块）**
- **估时**

---

## 项目现状快照

| 维度 | 现状 |
|---|---|
| 测试 | 覆盖后端 API、WebSocket 状态机、导出、上传、鉴权和前端关键行为 |
| REST 端点 | 覆盖鉴权、上传、历史、导出、声纹、LLM 和设置 |
| 音频格式 | 7 种（wav/mp3/m4a/flac/ogg/aac/wma） |
| 导出格式 | 4 种（SRT/VTT/MD/JSON）|
| 语言 | zh + en |
| ASR 模型 | Qwen3-ASR / SenseVoice / Paraformer / Paraformer Streaming，可热切 |
| 声纹模型 | 3 个可选（CamPlus/ERes2NetV2/Wespeaker），可热切 |
| 数据库 | SQLite 单库 |
| 用户/认证 | 本地优先的轻量账号和 JWT 鉴权 |
| 移动端 | 基础响应式布局 |

---

## 优先级 1 — 快速赢（1-2 天/项，ROI 极高）

### 1.1 WebSocket 自动重连 ✅ 已完成

**状态**：Vue 版前端已在 `web/src/ws/liveStream.ts` 实现指数退避重连。网络抖动时会尝试 1/2/4/8/16 秒重连，鉴权失败则进入 `auth-failed`。

**当前实现**：
```js
// web/src/ws/liveStream.ts
if (this.attempts >= 5) {
  this.opts.onState('reconnecting')
  return
}
const delay = 1000 * Math.pow(2, this.attempts)
this.attempts++
this.opts.onState('reconnecting')
this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
```

**影响**：100% 真实用户，影响录制连续性。

**完成说明**：已由 Vue WebSocket 客户端接管；后续只需补充更明显的 UI 提示。

---

### 1.2 字级别时间戳

**痛点**：Qwen3-ASR 自身支持 word_timestamps，**后端没暴露**。结果：
- SRT/VTT 字幕只能按 segment 切（精度差，几秒一卡）
- 前端无法做"卡拉 OK 式"hover 高亮
- 用户想跳到"刚刚说的那句话"做不到

**实现**：
- `engine/asr_engine.py:run_asr` 调 `qwen_asr.transcribe(..., word_timestamps=True)`
- response schema 加 `words: [{text, start, end}]`
- 前端 transcript 视图 hover 文字 → 跳音频位置
- SRT/VTT exporter 改用字级而非 segment 级

**影响**：解锁精确字幕 + 音频回放 UX + 第三方视频工具兼容性（Premiere/FCP 字幕轨）。

**估时**：1.5 天

---

### 1.3 说话人合并 / 拆分

**痛点**：CamPlus 行业通病 — 同一人在音频条件变化时被识别成 2 个说话人（"Spk_001" / "Spk_007"）。现在用户**无法修正**：
- 改名：✓ 已有
- 合并：❌ 没有
- 拆分（某段归错人）：❌ 没有

**实现**：
- `POST /v1/speakers/merge` body: `{target_id, source_ids: [...]}`
  - ChromaDB: 把 source_ids 的所有 embedding 复制到 target_id
  - SQLite: `UPDATE segments SET speaker_id=target_id WHERE speaker_id IN source_ids`
- `POST /v1/speakers/{id}/split` body: `{segment_ids: [...], new_speaker_id: "Spk_xxx"}`
- detail 页每个 segment 加"换说话人"下拉

**影响**：核心使用场景，**没这个用户会一直烦**。从一次性工具变可修正工具。

**估时**：2 天

---

### 1.4 端到端 WebSocket 状态机测试

**痛点**：38 个 test 里**没有** `test_websocket_realtime.py`。当前核心链路（STATE_SILENCE ↔ STATE_SPEECH、跳帧、SequenceMatcher 增量文本）只靠手动浏览器测试。重构时会回归，无人发现。

**实现**：`tests/test_websocket_realtime.py`
- mock 音频流（16kHz PCM）
- 验证 SILENCE ↔ SPEECH 状态转换
- 验证 `silence_frame_count >= 3` 触发识别
- 验证 `SequenceMatcher` 增量文本提取
- 验证 `inference_lock` 串行化
- 验证 `skip_frame_threshold` 跳帧

**影响**：防止未来重构改坏核心链路。

**估时**：1.5 天

---

### 1.5 移动端响应式

**痛点**：当前 56px 左侧 nav + `max-width: 1480px` 是桌面设计。手机/平板打开要么挤一坨，要么滚动混乱。**会议场景很多手机用户**（出差/在家/通勤）。

**实现**：CSS `@media (max-width: 768px)`：
- 左侧 nav 改底部 tab bar
- `live-grid` 单列堆叠
- font-size 已经 `clamp()`，调 padding
- detail 页两列布局改单列

**估时**：1 天

---

## 优先级 2 — 战略功能（1-2 周/项）

### 2.1 实时翻译（zh ↔ en）

**痛点**：跨语言会议双方语言不同时（如中英双语团队），**这是杀手锏**。当前只输出源语言。

**实现**：
- 后端：每个 segment 识别后调翻译（NLLB-200 本地 / Qwen-MT 云）
- `inference_lock` 已有结构，asr + 翻译可并发（不同模型）
- 新字段 `translated: {lang, text}` 加到 segment schema
- 前端 detail 页两列对照显示
- 设置页加目标语言选择

**离线 vs 云**：
- 离线：NLLB-200-distilled-600M（1.5GB，CPU 可跑）
- 云：Qwen-MT / DeepL（用户自配 API key）

**影响**：打开**国际市场**。中文用户做英文会议，英文用户做中文会议都覆盖。

**估时**：2 周（含模型选型 + 增量翻译 pipeline）

---

### 2.2 说话人全文搜索

**痛点**：库里有 100 个会话、50 个说话人，找"3 周前张老师说过 X 的地方"要逐个翻 detail 页。`library.search` UI 占位但没接上。

**实现方向**：
- SQLite FTS5 虚表同步 `segments.text`
- `GET /v1/search?q=...&session_id=...&speaker_id=...&limit=50`
- 前端历史页搜索框接入
- 命中显示 segment、snippet 高亮和跳转链接

**关键实现细节**:
- FTS5 用 **contentless 模式**(`content=''`):索引存,但 content 仍由 segments.text 提供
  - 关键:contentless 才支持 `'delete'` / `'delete-all'` 命令(否则 cascade DELETE 报 SQL logic error)
- 分词用 **trigram**:3 字符三元组,中文 3+ 字命中率高,2 字走 LIKE 兜底
- snippet 自造(contentless 不支持 `snippet()` 函数):在 text 上找 q 位置 + 前后 8 字符

**影响**：从"档案柜"变"搜索引擎"，长期价值高。

**未来增强**(可作为 v0.5 候选):
- 中文分词:接 jieba 提升 2 字搜的命中率
- 上下文 ±2 段:当前只显示 hit 段本身,没扩上下文
- 模糊匹配:typo 容忍

**估时**：3 天

---

### 2.3 系统音频采集（loopback）

**痛点**：浏览器 `getUserMedia` 只能录麦克风。Zoom/Meet/钉钉会议**远端声音**是电脑播放的，需要 loopback 设备（Windows WASAPI / macOS Soundflower / Linux PulseAudio monitor）。

**实现**：
- 前端：`getDisplayMedia({video: true, audio: true})`（视频可丢弃，只要 audio）— 主流浏览器已支持
- macOS 用户：装 BlackHole 虚拟音频设备
- 配合 UI 引导：第一次用弹窗告诉用户怎么选音频源

**影响**：会议场景的**根本痛点** — 现在用户得用笔记本麦克风远距离收音，杂音大。

**估时**：1 周（含跨平台测试 + 文档）

---

### 2.4 说话人声纹库导出 / 导入

**痛点**：团队场景（实验室 / 部门）想共享声纹库，但每人本地独立。现在只能逐个 enroll。

**实现**：
- `GET /v1/speakers/export?fmt=zip` — 返 zip（SQLite dump + ChromaDB snapshot）
- `POST /v1/speakers/import` — 接 zip，合并（按 ID 冲突检测）
- 加密 + 签名（涉及生物特征）
- 前端设置页 "Export Library" / "Import Library" 按钮

**影响**：从"个人工具"变"团队基础设施"。

**估时**：1 周

---

### 2.5 PWA + 离线

**痛点**：手机浏览器体验差，不能离线，不能添加到桌面。

**实现**：
- `manifest.json` + Service Worker 缓存静态资源（api.js / i18n.js / util.js / index.html / 字体）
- 离线时显示 cached UI（API 不可用提示）
- 录音缓冲在 IndexedDB，恢复网络后批量上传

**影响**：移动场景完整化。配合 #2.3 loopback 就能"手机远端采音 → 主机转写"。

**估时**：1 周

---

## 优先级 3 — 大赌注（1 月+）

### 3.1 多用户模式 + 简易 auth

**痛点**：当前是单用户工具。多用户场景（家庭/团队）数据混在一起，**没有隔离**。

**实现**：
- `users` 表 + API key 模式（机器友好）+ session cookie（人类友好）
- `sessions.user_id` 外键
- SQLite → PostgreSQL（SQLAlchemy 抽象迁移）
- 数据隔离 + GDPR 友好删除（`DELETE /v1/users/{id}/data`）

**影响**：解锁 SaaS 化可能。但**项目定位是本地隐私**，加 auth 需明确"不强制账号，账号是可选"。

**估时**：1 个月

---

### 3.2 会议自动启动（Calendar / Zoom 集成）

**痛点**：用户经常忘了开录音，会议结束才后悔。

**实现**：
- Google Calendar webhook：会议开始前 5 分钟自动开始
- Zoom RTMS（Real-Time Media Stream）API：直接拉 Zoom 远端音频流，**零本地资源**
- 钉钉 / 飞书 类似
- 需要 OAuth + 开发者账号审批

**影响**：会议场景**根本 UX 革命**。但接入门槛高（Zoom RTMS 还在邀测）。

**估时**：1.5 月（含多平台适配）

---

### 3.3 自定义 ASR 微调

**痛点**：通用模型在长尾领域（医学/法律/技术会议）精度低。

**实现**：
- 用户上传 1h+ 标注音频（项目本身就有 → 反馈闭环）
- LoRA 微调 Qwen3-ASR（开源 LLaMA-Factory 工具链）
- 保存到 `models/custom/{user_id}/`
- 前端模型管理 UI

**影响**：从"通用工具"变"领域优化平台"。**契合 v0.2 已经有 LLM 接入**的扩展方向。

**估时**：1.5 月（含 UI + 训练 pipeline）

---

## 优先级 4 — 基础设施 / DX（持续投入）

### 4.1 文档

- [ ] `CONTRIBUTING.md`（开发约定 / 测试要求 / 提 PR 流程）
- [ ] `CHANGELOG.md`（语义化版本，从 v0.3 开始）
- [ ] `docs/ARCHITECTURE.md`（将现有架构说明正式化）
- [ ] `docs/MODELS.md`（ASR / 声纹模型选型指南，参考 4.6）
- [ ] README 顶部加架构图 + 截图 GIF
- [ ] FastAPI `/docs` 打开作为 API 参考

**估时**：3 天

### 4.2 CI 增强

- [ ] `ruff check` + `black --check` + `mypy app/`
- [ ] 测试覆盖率 badge
- [ ] Dependabot（`/.github/dependabot.yml`）
- [ ] Docker 镜像构建并 push 到 ghcr.io

**估时**：2 天

### 4.3 可观测性

- [ ] 结构化 JSON 日志（`structlog`）替代 `logging.basicConfig`
- [ ] Prometheus `/metrics` 端点（ASR RTF / WebSocket 连接数 / speaker 识别率）
- [ ] 请求 trace_id 串到日志
- [ ] 错误上报（前端 console 错误 → 后端 `/v1/telemetry`）

**估时**：4 天

### 4.4 Alembic 数据库迁移

当前 schema 仍以 `CREATE TABLE IF NOT EXISTS` 为主，**没有版本管理**。改 schema 时老库会崩。

**估时**：2 天

### 4.5 性能 / 扩展性

- [ ] Redis 缓存层（重复查询 + 限流 state）
- [ ] 后端任务队列（Celery / RQ）处理长上传 + LLM 摘要
- [ ] WebSocket 多 worker 扩展（Redis pub/sub 替代内存队列）

**估时**：1-2 周

### 4.6 ASR 模型可热切

**状态**：已完成。

当前通过 `ASREngineManager` 支持 Qwen3-ASR / SenseVoice / Paraformer / Paraformer Streaming 动态切换。新模型加载成功前旧 ASR 保持可用,加载失败不会影响当前服务。设置页已经提供确认弹窗和依赖缺失提示。

---

## 不做的事（明确取舍）

| 不做 | 理由 |
|---|---|
| ❌ Mobile 原生 app | PWA + 响应式 + loopback 已覆盖 80% 场景，开发 ROI 差 |
| ❌ 多 LLM provider 抽象 | 定位**本地隐私**，加云 LLM provider 破坏核心卖点 |
| ❌ 插件市场 | 用户基数未到，运营成本高 |
| ❌ 实时协作（多人同编辑） | CRDT 实现复杂，需求未验证 |
| ❌ 浏览器扩展 | 已有 PWA 路径，扩展增加维护面 |
| ❌ 自动说话人匿名化 | 跟"识别说话人"的核心功能冲突 |
| ❌ 视频理解（唇语/表情） | 偏离音频产品定位，复杂度爆炸 |

---

## 推荐首批（Top 3）

如果只做 3 件：

1. **WebSocket 自动重连**（#1.1）— 1 天，影响 100% 用户
2. **字级时间戳**（#1.2）— 1.5 天，解锁精确字幕 + 卡拉 OK UX
3. **说话人合并/拆分**（#1.3）— 2 天，解决核心痛点

理由：项目当前最大短板是**"录完发现说话人错了没救"**和**"网络抖动会断"**，这两个问题直接打击留存。功能再多，留不住用户也是白搭。

---

## 版本节奏建议

| 版本 | 时间 | 范围 |
|---|---|---|
| **v0.3.x** (patch) | 持续 | 稳定性、文档、模型能力说明、上传/实时细节修复 |
| **v0.4.0** (minor) | 后续 | 实时翻译、全文搜索增强、系统音频采集 |
| **v0.5.0** (minor) | 后续 | 团队声纹库、PWA、多用户数据隔离 |
| **v1.0.0** | 长期 | 会议集成、自定义 ASR 优化、生产级部署能力 |
