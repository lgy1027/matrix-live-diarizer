"""响应数据模型"""
from typing import Optional, Dict, List
from pydantic import BaseModel


class SegmentResult(BaseModel):
    """分段结果"""
    speaker: str
    text: str
    start_time: float
    end_time: float


class UploadResponse(BaseModel):
    """上传响应"""
    status: str
    filename: Optional[str] = None
    speaker: Optional[str] = None
    text: Optional[str] = None
    message: Optional[str] = None
    duration: Optional[float] = None
    segments: Optional[List[SegmentResult]] = None
    speakers: Optional[List[str]] = None


class EngineInfo(BaseModel):
    """声纹引擎信息"""
    name: str
    model: str
    description: str
    eer_voxceleb: str
    eer_cnceleb: str
    params: str
    speed: str


class ASRInfo(BaseModel):
    """ASR 信息"""
    name: str
    model: str
    description: str
    languages: str


class ModelsResponse(BaseModel):
    """模型信息"""
    current: str
    asr: ASRInfo
    speakers: Dict[str, EngineInfo]
