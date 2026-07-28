# 隐私

Matrix 本地优先，但非零存储。应用有意持久化数据，让会议在重启后仍可用。

## 本地存储

| 数据 | 默认位置 | 应用层加密 |
|---|---|---|
| 会议音频（含实时录音） | `data/media/` | 否 |
| 转写、纪要、人物、声纹 embedding | `data/matrix.db` | 否 |
| 非敏感设置（LLM endpoint/model/启用状态） | `data/matrix.db` | 否 |
| 可选的 LLM API key | `LLM_API_KEY` 进程环境 / `.env` | 否 |
| 模型文件 | 用户的 ModelScope/Hugging Face/Torch 缓存 | 否 |

请使用操作系统的全盘加密并保护用户账户。录音和声纹 embedding 属于生物敏感信息；仅在取得适当授权时注册声样。

## 网络行为

下载模型或 Python/npm 依赖时会发生联网。按所选能力，模型来源包括 ModelScope、Hugging Face、Torch Hub；pyannote 另需用户接受其 gated 模型条款并提供 `HF_TOKEN`。

LLM 功能默认关闭。读取 `/v1/llm/status` 和保存 LLM 设置不会连接配置的 endpoint。点击「测试连接」会发送一次不含会议文本的最小请求，可能产生 provider 用量。在已启用的外部 OpenAI 兼容 endpoint 下生成摘要、行动项或纪要时，转写文本和 prompt 会发送到该 endpoint；应用不会附上音频和声纹 embedding。

LLM API key 从 `LLM_API_KEY` 读取，不写入 SQLite、不返回给浏览器。请把 `.env`、进程环境、备份和诊断包当机密保护。

本仓库不含产品分析或遥测 SDK。服务日志可能含运维元数据和错误，但不应记录音频或 API key。

## 删除

删除会议会移除其数据库记录和应用管理的音频。删除人物会移除已注册的声样文件，并把该人物从会议中摘除（不删除会议本身）。删除整个 `data/` 前请先停服务，以清除所有受管产品数据。模型缓存和 `.env` 独立存放，需要时须单独删除。

当前不提供自动备份或留存清理。备份、留存、授权与合规义务由用户自行承担。
