"""Durable local processing job API."""
from fastapi import APIRouter, HTTPException, Query, Request


router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(request: Request, limit: int = Query(100, ge=1, le=200)):
    items = request.app.state.job_repo.list(limit=limit)
    return {"total": len(items), "items": items}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request):
    job = request.app.state.job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    if not request.app.state.job_repo.request_cancel(job_id):
        raise HTTPException(status_code=409, detail="任务不存在或已结束")
    return {"message": "已请求取消"}


@router.post("/{job_id}/retry")
def retry_job(job_id: str, request: Request):
    if not request.app.state.job_repo.retry(job_id):
        raise HTTPException(status_code=409, detail="只有失败或已取消任务可以重试")
    runner = getattr(request.app.state, "job_runner", None)
    if runner is not None:
        runner.notify()
    return request.app.state.job_repo.get(job_id)
