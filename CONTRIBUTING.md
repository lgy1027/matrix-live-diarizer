# Contributing

感谢你愿意改进 Matrix Live Diarizer。这个项目的核心目标是: 本地优先、模型能力说清楚、默认可用。

## 开发流程

1. Fork 仓库并创建功能分支。
2. 安装依赖:
   ```bash
   pip install -r requirements.txt
   cd web
   npm ci
   ```
3. 修改代码后运行校验:
   ```bash
   npm run build
   cd ..
   python -m pytest
   ```
4. 提 PR 时说明:
   - 改了什么行为
   - 涉及哪些模型能力或部署场景
   - 是否影响实时流、上传离线处理、历史存档或鉴权

## 代码约定

- 后端配置放在 `app/config.py`,优先支持 `.env` / 环境变量。
- ASR 能力说明以 `/v1/models` 后端返回为准,不要在前端硬编码模型能力矩阵。
- ASR 与说话人识别职责分开: ASR 做转写,Speaker Engine / pyannote 做说话人相关能力。
- 新增用户可见行为时,尽量补测试;涉及历史库字段时,同步更新 repository 测试。
- 不要提交模型缓存、上传音频、SQLite 数据库、声纹库和本地 `.env`。

## 安全与隐私

默认假设音频和转写文本是敏感数据。新增网络调用、远程模型、日志字段或导出格式时,请在 PR 中说明数据会不会离开本机。
