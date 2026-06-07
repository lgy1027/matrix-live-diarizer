# 使用指南

本文档是详细使用教程（Web 界面 + 高级场景）。
**30 秒快速上手**请看 [README](../README.md)；**API 接口**请看 [API.md](API.md)。

---

## 1. Web 界面 5 步走

1. 启动后端：`python main.py`（等 `[ASR] 模型加载成功` 日志出现）
   - Mac M 系列卡住超过 90s：`ASR_DEVICE=cpu python main.py`
2. 浏览器打开 `web/index.html` 文件（**不是**访问 8000 端口，前端是纯静态）
3. 页面会自动连接 `ws://127.0.0.1:8000` 后端
4. 左侧 4 个标签：**Live**（实时） / **Library**（历史） / **Voice**（声纹库） / **Settings**（设置）
5. 默认语言为 **中文**（右上角切 EN）

> 💡 静态文件说明：`web/index.html` 用 `file://` 协议打开，不依赖后端部署前端。
> 后端只暴露 WebSocket + REST API（不托管前端）。

## 2. 实时转写（Live）

1. 点中间 **录音按钮**（琥珀色圆形）→ 浏览器弹麦克风权限 → 同意
2. 说话 → 转写实时显示在 Transcript 区域
3. 多人说话 → 顶部 `[Spk_xxx]` 标签自动切换
4. 再点一次录音按钮结束 → 会话自动存档到 Library

### 实时流配置

- 默认采样率 16kHz（浏览器自动降采样）
- 静音超过 3 秒自动结束识别
- 单段最大 5 秒强制识别（避免长段延迟）

![首页](images/home.png)

![录音识别](images/upload.png)

## 3. 文件上传

### 方式 A：Live 页右侧 "Quick Capture"

适合**临时单文件**：
1. 在 Live 页面右侧 "Quick Capture" 区域
2. 拖拽文件到 dropzone，或点击选择文件
3. 自动开始上传 + 处理
4. 完成后跳到 Library 详情页

### 方式 B：curl / API

适合**批量或脚本**：

```bash
# 启用说话人识别（默认）
curl -X POST "http://127.0.0.1:8000/v1/upload" \
  -F "file=@meeting.mp3"

# 关闭说话人识别（更快，纯转写）
curl -X POST "http://127.0.0.1:8000/v1/upload?enable_diarization=false" \
  -F "file=@lecture.mp3"
```

### 长音频自动分段

> 30 秒以上的音频自动按 30s + 1s 重叠分段处理。
> 相邻段的重叠文本自动合并去重。

## 4. 历史浏览（Library）

1. 左侧切到 **Library** 标签
2. 顶部统计：sessions 数 / 总时长 / voices 数
3. 搜索框支持按标题 / 文件名模糊搜索
4. 标签页：**All** / **Live** / **Upload** 过滤来源
5. 点击某条记录 → 进入详情页

### 详情页操作

- 全文转写（按说话人分组）
- 4 种导出：SRT 字幕 / WebVTT / Markdown / JSON
- 删除 / 重命名会话
- LLM 一键生成摘要 / 行动项 / 纪要（需先在 Settings 启用 LLM）

![说话人](images/voice.png)

## 5. 声纹库（Voice Library）

所有识别过的说话人都列在这里。

### 单个管理

点卡片右上角 **⋮** 菜单：
- **Rename** — 弹 Modal 输入新名字
- **Delete** — 弹确认后删除（同时清空 segments 引用）

### 批量选择（v0.2.1+）

1. 顶部点 **Select** 按钮 → 进入选择模式
2. 卡片左上角 checkmark 渐入
3. 点多个卡片 toggle 选中 / 取消
4. 顶部 toolbar：
   - **Select all** / **Deselect all** 切换
   - **Delete N** — 弹危险确认 → 真删（dry_run 预览影响范围）
   - **Cancel** / **ESC** — 退出选择模式

### 引擎切换（Settings）

点右上角齿轮 → **Speaker Engine** 区块：
- 列出 3 个引擎（CamPlus / ERes2NetV2 / Wespeaker）
- 点 "Activate" 运行时切换
- ⚠️ 切换后 `embedding_dim` 变化时（CamPlus 192 ↔ Wespeaker 256）会提示
  声纹数据不兼容，需要重新注册说话人

![设置](images/settings.png)

## 6. 高级场景

### 6.1 多人会议（会议场景）

- 会议时长建议 ≤ 1 小时（CLAUDE.md 限制）
- 上传时 `enable_diarization=true`（默认）
- 选 **CamPlus** 引擎（实时优先）
- 结束后用 Library 详情页生成 LLM 摘要

### 6.2 批量处理（演讲场景）

- 关闭说话人识别 `enable_diarization=false`（更准更快）
- 多个文件循环调用 `/v1/upload`
- 用 `/v1/history` API 列出所有会话

### 6.3 本地 LLM 增强

详见 [LLM_SETUP.md](LLM_SETUP.md)。推荐：
- 本地：Ollama + qwen2.5:1.5b（3GB 内存）
- 远程：LiteLLM 反代 + OpenAI/Claude（隐私护栏已开公网）

### 6.4 容器化部署

```bash
# 反向代理示例（nginx）
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# ⚠️ 必须配置 trusted_proxies,否则限流失效
# .env 改成包含 nginx IP
```

## 7. 数据管理

### 查看数据

```bash
# SQLite 转写 + 设置
sqlite3 data/matrix.db ".tables"
sqlite3 data/matrix.db "SELECT id, title, source FROM sessions LIMIT 10;"

# ChromaDB 声纹
ls -la engine/speaker/speaker_db/campplus/
```

### 删除数据

```bash
# 全部清除(下次启动重建)
rm -rf data/ engine/speaker/speaker_db/ uploads/

# 详细隐私说明
# https://github.com/lgy1027/matrix-live-diarizer/blob/main/docs/PRIVACY.md
```

### 备份

```bash
# 转写 + 设置
cp data/matrix.db backup-$(date +%Y%m%d).db

# 声纹(整个目录)
tar -czf speaker_db-$(date +%Y%m%d).tar.gz engine/speaker/speaker_db/
```

## 8. 故障排查速查

| 现象 | 原因 | 解决 |
|------|------|------|
| 启动卡 4+ 分钟 0% CPU | macOS MPS 加载死锁 | `ASR_DEVICE=cpu python main.py` |
| 上传无反应 | 浏览器 `change` 事件 | 已在 v0.2.1 修复，重启服务 |
| 同文件多次识别为不同人 | buffer 污染 | 已在 v0.2 修复 `use_buffer=False` |
| 实时连接断开 | mic 权限 / 网络 | 检查浏览器控制台 |
| LLM 显示不可用 | Ollama 未起 / endpoint 错 | `curl $LLM_ENDPOINT/models` |
| 浏览器 `WebSocket error` | 后端没启 / 端口错 | 看 README 启动日志 |

更多问题见 [README FAQ](../README.md#-常见问题) 和 [LLM_SETUP.md 故障排查](LLM_SETUP.md#故障排查)。
