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

- `docs/PRIVACY.md` — 隐私保证
- `docs/LLM_SETUP.md` — LLM 设置指南
- 更新 `README.md` (新功能)
- 更新 `CLAUDE.md` (新架构)

## [v0.2.1] - 2026-06-07

### 修复

- 数据库 `connect()` 双重 `try:` 语法错,导致服务启动崩溃
- `/v1/exports/{id}` `format=md` 拒绝(前端 README 写法)
- `PATCH /v1/sessions/{id}` `is_archived` 字段缺失,白名单允许但 schema 拒绝
- `/v1/upload` 0 字节文件返 500,提前 400

### 改进

- 前端默认语言 `en` → `zh`(项目面向国内用户)
- 详情页没带 `?id=` 时不再盲打 `/v1/sessions/null`,显示引导文案
- `escapeHtml` 实现收敛到 `Matrix.escape`,3 处去重
- `settings.js` `btn-switch` 改用 `Matrix.api.put`
- 删 3 个独立页面顶部"推荐使用主页面"冗余 banner

### 测试

- 新增 3 个测试:`test_export_md_alias_accepted` / `test_patch_session_archive_roundtrip` / `test_reject_empty_file`
- 5 个 pre-existing 失败测试已全部修复(原 NumPy 2.x / scipy 兼容问题)
- 总数:242 passed
- Playwright 4 页 + 4 视图 0 console error,0 HTTP 4xx-5xx

### 文档

- `README.md` 头部重写:30 秒价值主张 + 飞书/通义对比表 + 目标用户 + 5 分钟跑通
- `docs/USAGE.md` 修正"默认语言为英文"等过时表述
