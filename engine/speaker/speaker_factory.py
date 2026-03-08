"""声纹引擎工厂

使用方式:
  python main.py                          # 默认 CamPlus
  SPEAKER_ENGINE=eres2net python main.py  # ERes2NetV2
  SPEAKER_ENGINE=wespeaker python main.py # Wespeaker
"""
import os

ENGINE_CONFIG = {
    "campplus": {
        "name": "CamPlus",
        "model": "damo/speech_campplus_sv_zh-cn_16k-common",
        "description": "速度快，适合实时场景",
        "eer_voxceleb": "0.65%",
        "eer_cnceleb": "6.78%",
        "params": "7.2M",
        "speed": "快"
    },
    "eres2net": {
        "name": "ERes2NetV2",
        "model": "iic/speech_eres2netv2_sv_zh-cn_16k-common",
        "description": "SOTA 级别精度",
        "eer_voxceleb": "0.61%",
        "eer_cnceleb": "6.14%",
        "params": "17.8M",
        "speed": "中等"
    },
    "wespeaker": {
        "name": "ResNet34",
        "model": "iic/speech_resnet34_sv_zh-cn_3dspeaker_16k",
        "description": "经典稳定",
        "eer_voxceleb": "1.05%",
        "eer_cnceleb": "6.92%",
        "params": "6.34M",
        "speed": "快"
    }
}

ASR_CONFIG = {
    "name": "Qwen3-ASR",
    "model": "Qwen/Qwen3-ASR-0.6B",
    "description": "阿里通义语音识别模型",
    "languages": "52种语言/方言"
}


def get_engine_type() -> str:
    """获取当前引擎类型"""
    return os.environ.get("SPEAKER_ENGINE", "campplus").lower()


def get_speaker_engine():
    """返回声纹引擎实例"""
    engine_type = get_engine_type()
    
    if engine_type == "eres2net":
        print("[FACTORY] 使用 ERes2NetV2 引擎")
        from .eres2net_engine import ERes2NetEngine
        return ERes2NetEngine()
    elif engine_type == "wespeaker":
        print("[FACTORY] 使用 Wespeaker 引擎")
        from .wespeaker_engine import WespeakerEngine
        return WespeakerEngine()
    else:
        print("[FACTORY] 使用 CamPlus 引擎")
        from .campplus_engine import CamPlusEngine
        return CamPlusEngine()


def get_engine_info() -> dict:
    """获取当前引擎信息"""
    engine_type = get_engine_type()
    info = ENGINE_CONFIG.get(engine_type, ENGINE_CONFIG["campplus"]).copy()
    info["type"] = engine_type
    return info


def get_all_engines() -> dict:
    """获取所有引擎信息"""
    return {
        "current": get_engine_type(),
        "asr": ASR_CONFIG,
        "speakers": ENGINE_CONFIG
    }