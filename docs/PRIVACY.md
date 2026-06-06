# 隐私保证

Matrix Live Diarizer 承诺：**你的音频、文本、声纹向量、设置，永远不会离开你的电脑。**

## 我们不收集什么

- ❌ 不收集任何遥测
- ❌ 不调用任何云 API
- ❌ 不上传音频文件
- ❌ 不上传转写文本
- ❌ 不上传声纹向量
- ❌ 不记录你的 IP

## 数据存储位置

| 数据 | 位置 | 加密 |
|---|---|---|
| 转写文本 | `data/matrix.db` (SQLite) | 否（依赖磁盘加密） |
| 声纹向量 | `engine/speaker/speaker_db/` (ChromaDB) | 否 |
| 设置 | `data/matrix.db` (SQLite) | 否 |
| 上传临时文件 | `uploads/` (处理后立即删除) | 否 |

## 如何验证

1. **网络抓包**：运行 `python main.py` 后，用 Wireshark 抓取 loopback 流量 — 应该只有 127.0.0.1 的本地通信
2. **CI 审计**：`pytest tests/test_privacy_audit.py` 自动检查无公网调用
3. **代码审计**：`grep -rE "google-analytics|sentry" web/ app/` 应该返回空

## 唯一会联网的时刻

仅在**首次启动**下载模型时：
- `modelscope` 下载 Qwen3-ASR
- `torch.hub` 下载 Silero VAD

下载完成后可**永久断网**使用。

## LLM 隐私

LLM 网关在启动时验证 endpoint：
- ✅ 允许：`127.0.0.1`, `localhost`, `::1`, 私有 IP (RFC1918)
- ❌ 拒绝：公网 IP / 公网域名（DNS 解析后）

如果你在 `settings.html` 配置了 `https://api.openai.com`，服务**直接拒绝启动**。

## 删除所有数据

```bash
rm -rf data/ engine/speaker/speaker_db/
```

下次启动会重建空数据库。
