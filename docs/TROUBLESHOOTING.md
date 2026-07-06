# Troubleshooting

## 启动卡住或首次启动很慢

首次启动会下载 ASR、VAD、声纹模型,耗时取决于网络。macOS MPS 上如果 Qwen3-ASR 加载长期卡住,先用 CPU 验证:

```bash
ASR_DEVICE=cpu python main.py
```

Docker 用户可看日志:

```bash
docker compose logs -f
```

## 前端打不开

源码运行需要先构建前端:

```bash
cd web
npm ci
npm run build
cd ..
python main.py
```

然后访问 `http://127.0.0.1:8000/`。不要直接打开旧的 `web/index.html`。

## 局域网访问失败

局域网部署建议显式配置:

```bash
DEPLOYMENT_MODE=lan
JWT_SECRET=<32字节以上随机字符串>
ALLOWED_ORIGINS=http://192.168.1.10:8000
```

手机浏览器录音通常要求 HTTPS 或 localhost 安全上下文。局域网 HTTP 页面可能无法使用麦克风。

## FunASR 相关模型不可用

SenseVoice / Paraformer / Paraformer Streaming 需要 `funasr`。Windows + Python 3.13 可能因为 `editdistance` wheel 缺失安装失败,建议使用 Python 3.10-3.12 或 Docker。

```bash
pip install funasr
```

## 字级时间戳没有出现

只有 Qwen3-ASR 路径支持当前的 ForcedAligner 字级时间戳:

```bash
ASR_ENGINE=qwen3
ASR_WORD_TIMESTAMPS=true
```

FunASR 系列目前按段返回结果。设置页显示的能力来自后端 `/v1/models`;如果你的部署做了自定义适配,可以用 `ASR_CAPABILITIES_JSON` 或 `ASR_CAPABILITIES_FILE` 覆盖能力说明。

## 多人会议说话人不准

实时模式是短片段声纹匹配,适合单人/双人参考标签,不等同于离线全局 diarization。多人会议建议上传完整录音并使用:

```text
POST /v1/upload?diarization=pyannote
```

需要配置 `HF_TOKEN` 并接受 pyannote 模型条款。

## 声纹注册上传失败

`/v1/speakers/enroll` 面向 1-30 秒示例音频,大小上限是 50MB。超过此范围请先裁剪音频;完整会议录音应使用 `/v1/upload`。

## Docker 访问不了宿主机 Ollama

容器里的 `127.0.0.1` 是容器自身。把 LLM endpoint 改为:

```bash
LLM_ENDPOINT=http://host.docker.internal:11434/v1
```

## 登录后提示必须改密

这是预期行为。默认账户 `admin/admin` 首次登录必须修改密码。局域网或公网部署前还要设置 `JWT_SECRET` 并收紧 `ALLOWED_ORIGINS`。
