"""一键注入示例转写数据 — 首次试用快速看到效果

用法:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --force
    python scripts/seed_demo_data.py --no-audio
"""
import argparse
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# 允许从仓库根目录运行
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config import config  # noqa: E402
from app.repositories.database import Database  # noqa: E402
from app.repositories.meetings import MeetingRepository  # noqa: E402

DEMO_AUDIO = [
    {
        "id": "demo_lecture_001",
        "url": "https://archive.org/download/Stanford_CoursE_101_Lec/Stanford_CoursE_101_Lec_01_64kb.mp3",
        "title": "示例: Stanford 公开讲座片段",
        "source": "upload",
        "license": "Public Domain (CC0)",
    },
    {
        "id": "demo_poetry_001",
        "url": "https://archive.org/download/short_poetry_022_libravox/shortpoetry_022_01_64kb.mp3",
        "title": "示例: LibriVox 诗歌朗读",
        "source": "upload",
        "license": "Public Domain",
    },
]


def download_to_temp(url: str, max_bytes: int = 200 * 1024 * 1024) -> Path:
    """下载 URL 到临时文件,带超时 + SSL 校验 + 大小限制

    Returns:
        临时文件路径,调用方负责 unlink。失败时自动清理。
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    tmp = Path(tmp_path)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Matrix-Seed/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            # 非数字 Content-Length 一律按未知处理,靠下载累计字节兜底
            try:
                content_length = int(resp.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                content_length = 0
            if content_length > max_bytes:
                tmp.unlink(missing_ok=True)
                raise ValueError(
                    f"文件过大: {content_length // 1024 // 1024}MB > "
                    f"{max_bytes // 1024 // 1024}MB"
                )
            downloaded = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        f.close()
                        tmp.unlink(missing_ok=True)
                        raise ValueError(
                            f"下载超过 {max_bytes // 1024 // 1024}MB 限制,中止"
                        )
                    f.write(chunk)
    except (urllib.error.URLError, ssl.SSLError, TimeoutError):
        tmp.unlink(missing_ok=True)
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def is_demo_meeting(meeting: dict) -> bool:
    """判断是否是示例会议(标题以"示例:"开头)。"""
    return (meeting.get("title") or "").startswith("示例:")


def main():
    parser = argparse.ArgumentParser(description="注入示例转写数据")
    parser.add_argument("--force", action="store_true", help="删旧示例重新生成")
    parser.add_argument("--no-audio", action="store_true", help="跳过下载,只插空 session")
    args = parser.parse_args()

    db = Database(config.storage.db_path)
    db.init_schema()
    repo = MeetingRepository(db)

    # 检查已有示例
    existing = [s for s in repo.list() if (s.get("title") or "").startswith("示例:")]
    if existing and not args.force:
        print(f"已存在 {len(existing)} 个示例会话,跳过。用 --force 重新生成。")
        for s in existing:
            print(f"  - {s['title']} ({s['id']})")
        return 0

    if args.force and existing:
        for s in existing:
            repo.delete(s["id"])
            print(f"  已删除: {s['title']}")

    if args.no_audio:
        print("--no-audio 模式: 跳过下载,只注入空 session")
        for demo in DEMO_AUDIO:
            sid = repo.create(source=demo["source"], title=demo["title"])
            print(f"  ✓ {demo['title']} ({sid})")
        print("\n完成!")
        return 0

    # 真实转写模式:下载音频到 media 目录持久化(不删),由 job_runner 转写。
    # 注:不在此加载 ASR/声纹引擎 —— 脚本只建会议占位,真实转写由服务启动后
    # job_runner 领出 job 完成,加载引擎会强制下载 1.8GB 模型且全程未使用。
    media_dir = Path(config.storage.media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)

    for demo in DEMO_AUDIO:
        print(f"\n处理: {demo['title']}")
        print(f"  URL: {demo['url']}")
        print(f"  License: {demo['license']}")
        try:
            tmp = download_to_temp(demo["url"])
            print(f"  下载完成: {tmp.stat().st_size // 1024} KB")
            # 持久化到 media 目录(不入 uploads,job_runner 直接用该路径),
            # 否则临时文件被删后 job_runner 领出必然 "meeting audio not found"。
            persistent = media_dir / f"{demo['id']}.mp3"
            tmp.replace(persistent)
            # 建会议 + job,等 JobRunner 处理(本脚本不直接调 meeting_processor,
            # 因其依赖运行时 DB/runtime 注入;仅创建会议占位,真实转写请用
            # POST /v1/meetings/upload 或运行服务后手动触发)
            meeting_id, job_id = repo.create_with_job(
                source=demo["source"],
                title=demo["title"],
                audio_path=str(persistent),
                status="processing",
            )
            print(f"  ✓ 已建示例会议 {meeting_id} (job={job_id})")
            print("    启动服务后由 job_runner 自动转写,或在前端手动 reprocess")
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            print("  跳过此条")

    print("\n完成!启动服务查看示例会议。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
