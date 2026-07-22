<div align="center">

# Matrix Live Diarizer

本机优先的会议录音转写工具 · 默认数据不外传 · 上传多人分离 + 实时字幕 + 声纹匹配

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.12-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
![Status](https://img.shields.io/badge/status-beta-blue.svg)

[English](README.en.md) · [使用说明](docs/USAGE.md) · [隐私](docs/PRIVACY.md) · [安全](docs/SECURITY.md) · [API](docs/API.md) · [模型](docs/MODELS.md)

</div>

> 这是一份 beta 阶段的本地单机工具,适合在受信任的机器上试用和改进。当前不面向公网部署、多租户、合规存档或自动身份判定。

## 它解决什么

把"一段会议录音"变成"带说话人归属、可校正、可导出"的结构化纪要，**音频和转写永远不出本机**。飞书/讯飞/在线 ASR 都要把音频传上云——本项目不上传音频。LLM 纪要可选本机 Ollama，公网 LLM 只在你显式允许时发送转写文本（永不发音频、永不发声纹）。

两条路径合一，覆盖会议从现场到会后的全程：

- 📤 **上传录音（会后高质量处理）**：解码 → ASR → 可选 pyannote 多人分离 → 声纹匹配已登记人物 → 入库 → 校正/纪要/导出。
- ⚡ **实时字幕（会议进行中）**：浏览器录音 → VAD 切段 → ASR → 声纹识别已登记人物 → 边说边出，落段入库。

## 核心能力

- 🖥️ **本地优先**：默认全本机推理，下载模型后可在无网环境运行（LLM 关闭时）。
- 👥 **多人说话人分离**：上传会议模式用 pyannote community-1 切出匿名说话人 turn。
- 🧬 **声纹匹配**：把匿名 `Spk_01` 按严格阈值匹配到已登记人物，可随时人工纠正，**不是身份认证**。声样支持**上传文件或浏览器在线录音**注册。
- 📝 **可校正纪要**：双击改文稿、批量重指说话人、合并/拆分说话人、生成/编辑摘要（LLM 或本地 TextRank 兜底）。
- 📤 **多格式导出**：Markdown / SRT / VTT / JSON。
- 🔧 **可切换引擎**：ASR（Qwen3-ASR / SenseVoice / Paraformer）、声纹（CamPlus / ERes2Net / Wespeaker）运行时可切。

## 产品边界

- 上传录音做会后高质量处理（多人分离 / 纪要 / 导出）；实时模式做会议进行中的近实时字幕。
- "说话人分离"只产生匿名标签；声纹匹配可按严格规则自动显示已登记人物，但不构成身份认证，且可随时纠正。
- 未配置 pyannote 时，会议仍可完成转写，但保持匿名并明确提示分离不可用。
- 默认数据保存在本机且不启用 LLM。首次启动下载模型时会联网。
- 不建议直接暴露到公网，也不承诺满足医疗、法律等受监管行业要求。

> **关于项目名**：实时与上传是同一会议的两个入口，均为一等功能。多人说话人分离（diarization）在上传模式完成；实时模式靠声纹识别已登记说话人，不做多人分离。

## 界面预览

<div align="center">
  <img src="docs/images/PRIVATE-MEETING-WORKSPACE.png" alt="会议工作区" width="100%">
  <p><b>会议工作区</b> · 转写、校正、说话人归属、纪要与导出,全程本地</p>
</div>

<table>
  <tr>
    <td width="50%" align="center"><b>实时字幕</b></td>
    <td width="50%" align="center"><b>会议库</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/Live-Transcription.png" alt="实时字幕" width="100%"></td>
    <td><img src="docs/images/Meetings.png" alt="会议库" width="100%"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><b>人员声样（含在线录音）</b></td>
    <td width="50%" align="center"><b>引擎与设置</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/People.png" alt="人员声样" width="100%"></td>
    <td><img src="docs/images/settings.png" alt="设置" width="100%"></td>
  </tr>
</table>

## 核心流程

**上传录音（会后）**

1. 上传录音并选择"快速转写"或"会议模式"。
2. 后台任务完成解码、转写和可选的说话人分离。
3. 在会议详情中检查自动匹配、确认中置信度建议，并校正文稿。
4. 生成或编辑纪要，随后导出所需格式。

**实时字幕（会中）**

1. 浏览器授权麦克风并开始录音。
2. VAD 自动切段、ASR 实时转写、声纹识别已登记说话人，边说边出。
3. 结束录音后落段入库，与上传会议进入同一套校正/纪要/导出流程。

人物声音样本属于可选的辅助匹配信息。系统仅在模型兼容、语音和样本充足、严格阈值通过时自动显示姓名；其他情况保持建议或匿名。

## 快速开始

要求 Python 3.10–3.12、Node.js 20+ 和 FFmpeg。首次运行需要下载模型。

```bash
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
python main.py
```

浏览器打开 `http://127.0.0.1:8000`。默认只监听本机回环地址。默认账户 `admin/admin`，首次登录强制改密。

项目处于 beta 阶段,接口趋于稳定但仍可能调整,请勿将其作为会议资料的唯一副本或长期归档系统。

Docker CPU 版：

```bash
docker compose up --build
```

需要自行发布多架构镜像时可使用 `docker buildx build --platform linux/amd64,linux/arm64 ...`；发布者必须分别验证目标架构，项目目前不提供预构建镜像承诺。

CPU 推理可能较慢；CUDA 用户建议使用本地 Python 环境并按 PyTorch 官方说明安装对应版本。

## 可选配置

复制 `.env.example` 为 `.env`。多数本机单机场景无需修改，常用项如下：

```dotenv
HOST=127.0.0.1
ASR_DEVICE=auto
ASR_ENGINE=qwen3
SPEAKER_ENGINE=campplus
HF_TOKEN=
LLM_ENABLED=false
```

`ASR_ENGINE` 可选 `qwen3` / `sensevoice` / `paraformer` / `paraformer_streaming`；`SPEAKER_ENGINE` 可选 `campplus` / `eres2net` / `wespeaker`。其余项见 `.env.example`。

**何时需要 `HF_TOKEN`**（其余情况留空即可）：

- ✅ 要用上传会议的**多人说话人分离**（pyannote community-1，gated 模型）→ 需填，且需在 HF 页面接受条款。
- ✅ 要启用**字级时间戳**（Qwen3-ForcedAligner）→ 建议填以避开 HF 限流。
- ❌ 只用实时字幕 / 快速转写 / 本机声纹匹配 → **不需要**。

只有明确部署到局域网时才使用 `HOST=0.0.0.0` 和 `DEPLOYMENT_MODE=lan`，并同时设置强随机 `JWT_SECRET`、可信 `ALLOWED_ORIGINS`。跨机器访问还需要 HTTPS（见下文「跨机器访问」）。

## 跨机器访问（可选）

默认 `HOST=127.0.0.1` 只监听本机——本机用 `http://127.0.0.1:8000` 即可，麦克风和上传都正常。

要从**别的机器**访问（上传录音、在线录音都要麦克风），浏览器要求 HTTPS：`http://IP` 非 localhost 下 `getUserMedia` 会被禁用。项目支持让服务直接跑 HTTPS 自签证书。请先确保系统已安装 OpenSSL，随后使用项目的跨平台 Python 脚本生成包含本机 IPv4 地址的证书。

macOS / Linux：

```bash
python3 scripts/gen_self_cert.py
ENABLE_HTTPS=1 HOST=0.0.0.0 \
DEPLOYMENT_MODE=lan ALLOWED_ORIGINS=https://<本机IP>:8000 \
python main.py
```

Windows PowerShell：

```powershell
python .\scripts\gen_self_cert.py
$env:ENABLE_HTTPS = "1"
$env:HOST = "0.0.0.0"
$env:DEPLOYMENT_MODE = "lan"
$env:ALLOWED_ORIGINS = "https://<本机IP>:8000"
python main.py
```

macOS / Linux 也可以继续使用兼容入口 `bash scripts/gen_self_cert.sh`。

浏览器访问 `https://<本机IP>:8000`，首次提示"不安全"点"高级 → 继续前往"即可。

## 数据和网络

- 会议音频：`data/media/`（上传录音原文件，按会议 id 命名）
- 人物声样音频：`data/media/voices/<person_id>/`
- 转写、人物、声纹向量、设置和 LLM API Key：`data/matrix.db`
- 模型缓存：默认在项目根 `models/`（可由 `MODELS_DIR` 配置）
- 可选公网 LLM：仅在用户显式允许时发送转写文本

这些数据默认不加密，请使用操作系统磁盘加密并保护本机账户。删除会议或人物会删除应用管理的对应音频文件；删除整个 `data/` 前应先停止服务。

## 开发验证

```bash
pytest -q --ignore=tests/test_smoke_boot.py
```

```bash
cd web
npm run check:i18n
npm run typecheck
npm run build
npm audit --omit=dev
```

真实模型冒烟测试会下载并加载大模型，因此常规 CI 默认不运行：`MATRIX_TEST_REAL_DEPENDENCIES=1 pytest tests/test_smoke_boot.py -v`。PowerShell 请先执行 `$env:MATRIX_TEST_REAL_DEPENDENCIES="1"`。

## 贡献

欢迎通过 Pull Request 贡献代码，流程与约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 问题反馈

- 缺陷或功能建议请提 [GitHub Issue](https://github.com/lgy1027/matrix-live-diarizer/issues)。
- 安全漏洞请按 [SECURITY.md](SECURITY.md) 的指引私下报告，不要在 Issue 中附带录音、转写或凭据。

## 许可证

项目代码采用 [MIT License](LICENSE)。模型权重和部分数据集拥有各自的许可证与使用条款，不随 MIT 自动授权；部署前请阅读 [模型说明](docs/MODELS.md) 并核对上游条款。
