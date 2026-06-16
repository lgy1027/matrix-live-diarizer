"""响应数据模型"""
from typing import Optional, Dict, List
from pydantic import BaseModel, Field, field_validator


class SegmentResult(BaseModel):
    """分段结果"""
    speaker: str
    text: str
    start_time: float
    end_time: float
    words: Optional[List[Dict]] = Field(
        None,
        description="字级时间戳 [{text, start, end}] — 仅 ASR_WORD_TIMESTAMPS=true 时返回",
    )


class UploadResponse(BaseModel):
    """上传响应

    整改: 新增 has_speech + warning 字段, 让用户知道上传是否真的识别出了语音.
    """
    status: str
    filename: Optional[str] = None
    speaker: Optional[str] = None
    text: Optional[str] = None
    message: Optional[str] = None
    duration: Optional[float] = None
    segments: Optional[List[SegmentResult]] = None
    speakers: Optional[List[str]] = None
    session_id: Optional[str] = None
    has_speech: bool = True
    warning: Optional[str] = None


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
    # 防日志注入 + 控制字符: 只允许可打印字符 + 空格
    # Bug-11: 增加 SQL 关键字拒绝,防止破坏性 SQL 注入 payload 通过 schema
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[\x20-\x7E一-鿿　-〿＀-￯]+$",
        description=(
            "说话人名称(1-100 字符,只允许可打印 ASCII / 中文 / 全角标点,过滤控制字符; "
            "拒绝包含 SQL 关键字的名称,如 DROP/DELETE/SELECT/INSERT/UPDATE/UNION 等)"
        ),
    )

    @field_validator("name")
    @classmethod
    def _reject_sql_keywords(cls, v: str) -> str:
        # Bug-11: 拒绝明显是 SQL 注入的字符串(ORM 自身已安全,这里是产品级防御)
        upper = v.upper()
        for kw in ("DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "UNION", "--", "/*"):
            if kw in upper:
                raise ValueError(
                    f"名称包含禁止关键字 {kw!r},请改用其他名称"
                )
        return v


class SpeakerDeleteResponse(BaseModel):
    """说话人删除响应

    整改: 默认 cascade_segments_cleared=True (与 POST /v1/speakers/cleanup cascade 一致),
    删除声纹时自动清空 segments.speaker_id 引用, 避免孤立 Spk_xxx 显示.
    """
    message: str
    cascade_segments_cleared: int = 0
    affected_sessions: int = 0


class SpeakerImpactResponse(BaseModel):
    """删声纹影响预览 (整改)

    segments_count: 引用此声纹的 segment 数 (清空后这些 segment.speaker_id 变 NULL)
    sessions_count: 引用此声纹的 session 数 (DISTINCT)
    """
    speaker_id: str
    segments_count: int
    sessions_count: int


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