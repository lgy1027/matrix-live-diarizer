# Matrix Live Diarizer 改进计划

## 功能增强

### 高优先级

- [x] **说话人管理**
  - 给说话人命名（如"张三"、"李四"）
  - 删除说话人
  - 查看说话人列表（支持按会话筛选）
  - API: `GET /v1/speakers`, `PATCH /v1/speakers/{id}`, `DELETE /v1/speakers/{id}`, `GET /v1/speakers/{id}`

- [ ] **导出功能**
  - 导出为 SRT/VTT 字幕格式
  - 带时间戳的纯文本
  - API: `GET /v1/export?srt=true&vtt=true`

### 中优先级

- [ ] **批量上传**
  - 支持同时上传多个文件
  - 队列管理，逐个处理

- [ ] **异步任务**
  - 上传大文件改为后台任务
  - 支持进度查询
  - API: `GET /v1/tasks/{id}`

- [ ] **音频可视化**
  - 显示音频波形
  - 标记不同说话人的时间段

## 用户体验

- [ ] **说话人面板** - 界面右侧显示已识别说话人列表，支持点击重命名
- [ ] **历史记录** - 保存转写历史到本地存储，支持搜索和回放
- [ ] **快捷键** - 空格开始/停止录音，Esc 清空终端
- [ ] **主题切换** - 深色/浅色主题可选

## API 扩展

```
GET    /v1/speakers              # 获取说话人列表（可按 session_id 筛选）
GET    /v1/speakers/{id}         # 获取单个说话人信息
PATCH  /v1/speakers/{id}         # 重命名说话人
DELETE /v1/speakers/{id}         # 删除说话人及其声纹
GET    /v1/export                # 导出转写结果
GET    /v1/tasks                 # 获取任务列表
GET    /v1/tasks/{id}            # 查询后台任务状态
```

## 基础设施

- [ ] **Docker 部署** - 提供 Dockerfile 和 docker-compose.yml
- [ ] **单元测试** - 补充 ASR/声纹引擎的 mock 测试
- [ ] **CI/CD** - GitHub Actions 自动测试和发布

## 性能优化

- [ ] **流式 ASR** - 利用 Qwen3-ASR 的流式能力，更低延迟
- [ ] **GPU 批处理** - 多个请求合并批处理，提升吞吐
- [ ] **模型预热** - 启动时预加载模型，避免首次请求慢

## 已完成

- [x] 长音频分段处理
- [x] 可选说话人识别 (enable_diarization)
- [x] 分段文本自动去重
- [x] Web 前端说话人识别开关
- [x] 自动重连机制
- [x] 队列优化和跳帧策略
