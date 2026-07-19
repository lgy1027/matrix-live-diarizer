"""本地模型目录解析器。

所有模型(ASR / VAD / 声纹 / pyannote)统一放在 ``config.models.models_dir`` 下,
按分类建子目录、每个模型一个目录:

    models/
      asr/Qwen3-ASR-0.6B/
      asr/Qwen3-ForcedAligner-0.6B/
      asr/SenseVoiceSmall/          # FunASR(modelscope 缓存结构)
      vad/silero-vad/
      speaker/camplus/
      speaker/eres2net/
      speaker/wespeaker/
      pyannote/speaker-diarization-community-1/

策略(本地优先):
1. 本地目录存在且非空 → 直接返回,纯离线加载。
2. 本地空 → 下载到本地目录(HF 用 local_dir 产出干净命名目录;modelscope
   下载到其缓存后 copytree 进本地;torch.hub 同理)。各库的现有缓存
   (~/.cache/...)会被复用,所以"自动迁移 copy" = 首次 resolve 时把缓存
   里的模型物化到 models/<cat>/<name>/,之后断网可用,无需重新下载。
"""
from __future__ import annotations

import logging
import os
import shutil

logger = logging.getLogger("Matrix_Models")


def models_root() -> str:
    """返回模型根目录的绝对路径(默认 ./models,可由 MODELS_DIR 覆盖)。"""
    return os.path.abspath(_cfg().models.models_dir)


def _cfg():
    from app.config import config  # 延迟 import,避免循环
    return config


def local_path(category: str, name: str) -> str:
    return os.path.join(models_root(), category, name)


def has_local(category: str, name: str) -> bool:
    p = local_path(category, name)
    return os.path.isdir(p) and bool(os.listdir(p))


def _ensure_parent(category: str, name: str) -> None:
    os.makedirs(local_path(category, name), exist_ok=True)


def _copytree(src: str, dst: str) -> None:
    """copytree,dirs_exist_ok=True,解析符号链接拷真实文件。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False)


# ---------- HF 模型(ASR / ForcedAligner / pyannote) ----------

def resolve_hf(repo_id: str, category: str, name: str, revision: str | None = None) -> str:
    """解析 HF 模型到 models/<category>/<name>/。

    本地存在 → 返回;否则 snapshot_download(local_dir=...) 物化到本地
    (HF 会复用 ~/.cache/huggingface 里的缓存,不重新下载,实现自动迁移)。
    """
    dst = local_path(category, name)
    if has_local(category, name):
        logger.info("[MODELS] HF %s/%s 已就绪(本地)", category, name)
        return dst
    _ensure_parent(category, name)
    from huggingface_hub import snapshot_download
    logger.info("[MODELS] 解析 HF %s → %s (复用缓存,物化到本地)", repo_id, dst)
    snapshot_download(repo_id, revision=revision, local_dir=dst)
    return dst


# ---------- ModelScope 模型(声纹) ----------

def _modelscope_cache_dir(model_id: str) -> str | None:
    """若 modelscope 缓存里已有该 model_id,返回其目录路径(干净 org/model)。

    缓存根尊重 MODELSCOPE_CACHE 环境变量(默认 ~/.cache/modelscope)。
    """
    root = os.path.expanduser(
        os.environ.get("MODELSCOPE_CACHE", "~/.cache/modelscope") + "/hub/models"
    )
    org, _, model = model_id.partition("/")
    if not model:
        return None
    # modelscope 把 repo id 里的 '.' 替换成 '___'(如 Qwen3-ASR-0.6B → Qwen3-ASR-0___6B)
    cand = os.path.join(root, org, model.replace(".", "___"))
    return cand if os.path.isdir(cand) else None


def resolve_modelscope(model_id: str, category: str, name: str, revision: str | None = None) -> str:
    """解析 ModelScope 模型到 models/<category>/<name>/。

    本地存在 → 返回;复用 modelscope 缓存 copytree 到本地;缓存没有则下载
    (modelscope snapshot_download 返回缓存目录,再 copy 进本地)。

    容错:任何阶段失败(如测试环境 fake modelscope、网络问题)都返回 dst,
    让上层 Model.from_pretrained 决定是否降级,而不是抛异常中断引擎初始化。
    """
    dst = local_path(category, name)
    if has_local(category, name):
        logger.info("[MODELS] MS %s/%s 已就绪(本地)", category, name)
        return dst
    # 1) 优先从已有缓存 copytree(自动迁移)
    cached = _modelscope_cache_dir(model_id)
    if cached:
        try:
            logger.info("[MODELS] 迁移 MS %s ← %s(缓存)", name, cached)
            _copytree(cached, dst)
            return dst
        except Exception as e:
            logger.warning("[MODELS] 迁移 MS %s 失败,回退到下载: %s", name, e)
    # 2) 缓存没有/迁移失败 → 下载到 modelscope 缓存,再 copy
    _ensure_parent(category, name)
    try:
        from modelscope import snapshot_download as ms_dl
        logger.info("[MODELS] 下载 MS %s (revision=%s)", model_id, revision)
        downloaded = ms_dl(model_id, revision=revision) if revision else ms_dl(model_id)
        if isinstance(downloaded, str) and os.path.isdir(downloaded):
            _copytree(downloaded, dst)
    except Exception as e:
        # 测试环境 fake modelscope / 网络失败:返回 dst(可能空),上层降级
        logger.warning("[MODELS] %s 下载失败,返回空本地目录让上层处理: %s", name, e)
    return dst


# ---------- Silero VAD(torch.hub) ----------

def _torch_hub_vad_cache() -> str | None:
    """若 torch hub 缓存里有 silero-vad 目录,返回路径。"""
    import glob
    root = os.path.expanduser("~/.cache/torch/hub")
    cands = sorted(glob.glob(os.path.join(root, "snakers4_silero-vad_*")))
    return cands[0] if cands else None


def resolve_silero_vad(name: str = "silero-vad") -> str:
    """解析 Silero VAD 到 models/vad/<name>/。

    本地存在 → 返回;复用 torch hub 缓存 copytree;缓存没有则 torch.hub
    在线下载后 copy(可能撞 GitHub 限流,但仅首次)。
    """
    category = "vad"
    dst = local_path(category, name)
    if has_local(category, name):
        return dst
    cached = _torch_hub_vad_cache()
    if cached:
        logger.info("[MODELS] 迁移 VAD ← %s(缓存)", cached)
        _copytree(cached, dst)
        return dst
    # 缓存没有 → 在线下载到 torch hub,再 copy
    import torch
    _ensure_parent(category, name)
    # 下载到默认 torch hub 缓存后取出路径
    torch.hub.load(
        repo_or_dir=f"snakers4/silero-vad:{os.environ.get('SILERO_VAD_REVISION', '76e3dc408eb2a5c655c34e230d2d5459b4439daa')}",
        model="silero_vad", trust_repo=True,
    )
    cached2 = _torch_hub_vad_cache()
    if cached2:
        _copytree(cached2, dst)
    return dst
