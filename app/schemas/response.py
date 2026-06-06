"""响应数据模型"""
from typing import Optional, Dict, List
from pydantic import BaseModel, Field


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
    session_id: Optional[str] = None


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


class SpeakerInfo(BaseModel):
    """说话人信息"""
    id: str
    name: str
    session_id: str
    sample_count: int
    last_update: float


class SpeakerResponse(BaseModel):
    """单个说话人响应"""
    speaker: SpeakerInfo


class SpeakerListResponse(BaseModel):
    """说话人列表响应"""
    speakers: List[SpeakerInfo]
    total: int


class SpeakerUpdateRequest(BaseModel):
    """说话人更新请求"""
    name: str = Field(..., min_length=1, max_length=100, description="说话人名称")


class SpeakerDeleteResponse(BaseModel):
    """说话人删除响应"""
    message: str


class EngineSwitchRequest(BaseModel):
    """引擎切换请求"""
    engine_type: str = Field(..., min_length=1, description="引擎类型: campplus/eres2net/wespeaker")


class EngineInfoExtended(BaseModel):
    """扩展的引擎信息（包含embedding维度）"""
    name: str
    model: str
    description: str
    eer_voxceleb: str
    eer_cnceleb: str
    params: str
    speed: str
    embedding_dim: int
    type: Optional[str] = None


class EngineSwitchResponse(BaseModel):
    """引擎切换响应"""
    success: bool
    engine_type: str
    engine_info: Optional[EngineInfoExtended] = None
    previous_type: Optional[str] = None
    embedding_dim_changed: bool = False
    previous_dim: Optional[int] = None
    new_dim: Optional[int] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    already_active: Optional[bool] = None


class EnginesListResponse(BaseModel):
    """引擎列表响应"""
    current: str
    engines: Dict[str, Dict]