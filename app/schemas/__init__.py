"""响应数据模型"""
from app.schemas.response import (
    UploadResponse,
    ModelsResponse,
    EngineInfo,
    ASRInfo,
    SegmentResult,
    SpeakerInfo,
    SpeakerResponse,
    SpeakerListResponse,
    SpeakerUpdateRequest,
    SpeakerDeleteResponse,
    SpeakerImpactResponse,
)

__all__ = [
    'UploadResponse', 'ModelsResponse', 'EngineInfo', 'ASRInfo', 'SegmentResult',
    'SpeakerInfo', 'SpeakerResponse', 'SpeakerListResponse', 'SpeakerUpdateRequest',
    'SpeakerDeleteResponse', 'SpeakerImpactResponse',
]