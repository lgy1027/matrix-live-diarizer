"""全文搜索 API(Roadmap #2.2)

GET /v1/search?q=...&session_id=...&speaker_id=...&limit=50
- FTS5 trigram 主路径 + LIKE 兜底(2 字 / 特殊字符)
- 命中含 snippet 高亮(<mark>...</mark>) + session 元数据
"""
from fastapi import APIRouter, HTTPException, Query, Request

from app.repositories.transcripts import TranscriptRepository

router = APIRouter()


@router.get("/v1/search")
def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="搜索关键词(3+ 字中文命中率高)"),
    session_id: str | None = Query(None, description="限定会话 ID(可选)"),
    speaker_id: str | None = Query(None, description="限定说话人 ID(可选)"),
    limit: int = Query(50, ge=1, le=200, description="返回数量上限"),
):
    """全文搜索 segments(命中含高亮 snippet + 跳转链接)

    返回结构:
    ```json
    {
      "query": "今天我们",
      "total": 5,
      "hits": [
        {
          "segment_id": 42,
          "session_id": "abc-123",
          "session_title": "会议1",
          "speaker_id": "Spk_xxx",
          "text": "今天我们讨论... ",
          "snippet": "今天我们讨论<mark>语音识别</mark>...",
          "start_time": 0.0,
          "end_time": 5.2,
          "jump_url": "/web/detail.html?id=abc-123&seg=42"
        }
      ]
    }
    ```
    """
    repo: TranscriptRepository = request.app.state.transcript_repo
    total, hits = repo.search_segments(q, session_id=session_id, speaker_id=speaker_id, limit=limit)

    # 加 jump_url 便于前端跳转 detail 页
    for h in hits:
        h["jump_url"] = f"/web/detail.html?id={h['session_id']}&seg={h['segment_id']}"

    return {
        "query": q,
        "total": total,
        "session_id": session_id,
        "speaker_id": speaker_id,
        "hits": hits,
    }
