"""响应数据模型"""
from typing import Optional, Dict
from pydantic import BaseModel


class UploadResponse(BaseModel):
    """文件上传响应"""
    status: str
    filename: Optional[str] = None
    speaker: Optional[str] = None
    text: Optional[str] = None
    message: Optional[str] = None


class EngineInfo(BaseModel):
    """引擎信息"""
    name: str
    model: str
    description: str
    eer_voxceleb: str
    eer_cnceleb: str
    params: str
    speed: str


class ASRInfo(BaseModel):
    """ASR 模型信息"""
    name: str
    model: str
    description: str
    languages: str


class ModelsResponse(BaseModel):
    """模型信息响应"""
    current: str
    asr: ASRInfo
    speakers: Dict[str, EngineInfo]