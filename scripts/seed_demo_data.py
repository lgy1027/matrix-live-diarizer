"""一键注入示例转写数据 — 首次试用快速看到效果

用法:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --force
    python scripts/seed_demo_data.py --no-audio
"""
import argparse
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
from app.repositories.transcripts import TranscriptRepository  # noqa: E402

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

    Args:
        url: 音频源 URL
        max_bytes: 最大下载字节数,默认 200MB(防止被劫持到 GB 级文件)

    Returns:
        临时文件路径,调用方负责 unlink
    """
    tmp = Path(tempfile.mkstemp(suffix=".mp3")[1])
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Matrix-Seed/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            content_length = int(resp.headers.get("Content-Length", 0))
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
    except (urllib.error.URLError, ssl.SSLError, TimeoutError) as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"下载失败: {e}") from e
    return tmp


def is_demo_session(session: dict) -> bool:
    """判断是否是示例 session(标题以"示例:"开头)"""
    return (session.get("title") or "").startswith("示例:")


def main():
    parser = argparse.ArgumentParser(description="注入示例转写数据")
    parser.add_argument("--force", action="store_true", help="删旧示例重新生成")
    parser.add_argument("--no-audio", action="store_true", help="跳过下载,只插空 session")
    args = parser.parse_args()

    db = Database(config.storage.db_path)
    db.init_schema()
    repo = TranscriptRepository(db)

    # 检查已有示例
    existing = [s for s in repo.list_sessions() if is_demo_session(s)]
    if existing and not args.force:
        print(f"已存在 {len(existing)} 个示例会话,跳过。用 --force 重新生成。")
        for s in existing:
            print(f"  - {s['title']} ({s['id']})")
        return 0

    if args.force and existing:
        for s in existing:
            repo.delete_session(s["id"])
            print(f"  已删除: {s['title']}")

    if args.no_audio:
        print("--no-audio 模式: 跳过下载,只注入空 session")
        for demo in DEMO_AUDIO:
            sid = repo.create_session(source=demo["source"], title=demo["title"])
            print(f"  ✓ {demo['title']} ({sid})")
        print("\n完成!打开 web/history.html 查看示例。")
        return 0

    # 真实转写模式
    print("加载 ASR + 声纹引擎...")
    from engine.asr_engine import ASREngine
    from engine.speaker.speaker_factory import SpeakerEngineManager
    from app.services.transcribe import transcribe_file

    asr = ASREngine()
    spk = SpeakerEngineManager.get_engine()

    for demo in DEMO_AUDIO:
        print(f"\n处理: {demo['title']}")
        print(f"  URL: {demo['url']}")
        print(f"  License: {demo['license']}")
        try:
            audio_path = download_to_temp(demo["url"])
            print(f"  下载完成: {audio_path.stat().st_size // 1024} KB")
            # 先建空 session 拿 id(转写用),再更新元信息
            sid = repo.create_session(source=demo["source"], title=demo["title"])
            result = transcribe_file(
                audio_path=str(audio_path),
                asr_engine=asr,
                spk_engine=spk,
                session_id=sid,
                sample_rate=config.audio.sample_rate,
            )
            # 写 segments
            for idx, seg in enumerate(result.segments):
                repo.insert_segment(
                    sid, idx, seg.text,
                    seg.start_time, seg.end_time,
                    speaker_id=seg.speaker_id,
                )
            print(f"  ✓ 注入完成 ({len(result.segments)} 段, {result.duration_sec:.1f}s)")
            audio_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            print(f"  跳过此条")

    print("\n完成!打开 web/history.html 查看示例。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
