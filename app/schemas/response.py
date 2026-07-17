"""Shared response models for runtime engine selection."""
from typing import Dict, Optional

from pydantic import BaseModel, Field


class EngineSwitchRequest(BaseModel):
    engine_type: str = Field(..., min_length=1)


class EngineInfoExtended(BaseModel):
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
    current: str
    engines: Dict[str, Dict]
