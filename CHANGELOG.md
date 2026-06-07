# Changelog

## [Unreleased] v0.2 - 2026-06-06

### 新增

- **4 种转写导出格式** (SRT / WebVTT / Markdown / JSON)
- **统计引擎** (说话人时长 / 字数 / 热词 / 静音比例)
- **转写历史** (SQLite 持久化，默认启用，可通过 `STORAGE_HISTORY_ENABLED` 关闭)
- **多页前端** (history / detail / settings)
- **可选本地 LLM 插件** (OpenAI 兼容协议 + 严格隐私护栏)
- **隐私审计测试** + GitHub Actions CI
- **隐私保证文档** (`docs/PRIVACY.md`) + LLM 设置指南 (`docs/LLM_SETUP.md`)

### 改进

- WebSocket 实时路径：支持命名会话 + 自动存档 segments
- 上传 API：返回 `session_id`，前端可跳转详情页
- 启动横幅增加 "🔒 完全离线" 提示

### 安全

- LLM endpoint 启动时校验，禁止公网地址
- CI 强制检查无遥测 SDK (`google-analytics`, `sentry`, `gtag` 等)
- 启动横幅明确"数据仅在本机处理"

### 架构变化

- 新增 `app/repositories/` 层 (SQLite + WAL 模式)
- 新增 `app/services/` 层 (exporter, statistics, llm_gateway)
- 新的 API 端点：`/v1/exports/{id}`, `/v1/history`, `/v1/sessions/{id}`, `/v1/llm/*`
- 前端拆为多页 + 路由 (FastAPI 挂载静态目录)

### 文档

- `docs/superpowers/specs/2026-06-06-产出型生产力工具设计.md` — 设计文档
- `docs/superpowers/plans/2026-06-06-产出型生产力工具.md` — 实施计划
- `docs/PRIVACY.md` — 隐私保证
- `docs/LLM_SETUP.md` — LLM 设置指南
- 更新 `README.md` (新功能)
- 更新 `CLAUDE.md` (新架构)

### 已知问题

- 5 个 pre-existing 测试因 NumPy 2.x 与 scipy 兼容问题失败（`test_engine_switch`, `test_exceptions`, `test_logging`, `test_upload_security`, `test_base_engine`）。CI 已临时 `--ignore` 这些文件，v0.3 应修复。
