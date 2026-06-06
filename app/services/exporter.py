"""导出器：SRT / WebVTT / Markdown / JSON"""
from typing import Iterable


def _format_srt_time(seconds: float) -> str:
    """SRT 时间码 HH:MM:SS,mmm"""
    ms_total = int(round(seconds * 1000))
    hours, rem = divmod(ms_total, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    """WebVTT 时间码 HH:MM:SS.mmm"""
    ms_total = int(round(seconds * 1000))
    hours, rem = divmod(ms_total, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def _speaker_label(speaker_id, speaker_aliases):
    if not speaker_id:
        return ""
    name = speaker_aliases.get(speaker_id, speaker_id)
    return f"[{name}] "


def _segment_text(seg, speaker_aliases, prefix_format: str) -> str:
    text = (seg.get("text") or "").strip()
    if not text:
        return ""
    label = _speaker_label(seg.get("speaker_id"), speaker_aliases)
    return label + text if prefix_format == "bracket" else f"{label}{text}".strip()


def export_srt(segments: Iterable[dict], speaker_aliases: dict) -> str:
    """SRT 字幕格式"""
    out_lines = []
    idx = 1
    for seg in segments:
        text = _segment_text(seg, speaker_aliases, "bracket")
        if not text:
            continue
        start = _format_srt_time(seg["start_time"])
        end = _format_srt_time(seg["end_time"])
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        out_lines.append(text)
        out_lines.append("")
        idx += 1
    return "\n".join(out_lines)


def export_vtt(segments: Iterable[dict], speaker_aliases: dict) -> str:
    """WebVTT 字幕格式"""
    out_lines = ["WEBVTT", ""]
    idx = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = _format_vtt_time(seg["start_time"])
        end = _format_vtt_time(seg["end_time"])
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        if seg.get("speaker_id"):
            name = speaker_aliases.get(seg["speaker_id"], seg["speaker_id"])
            out_lines.append(f"<v {name}>{text}</v>")
        else:
            out_lines.append(text)
        out_lines.append("")
        idx += 1
    return "\n".join(out_lines)


def _format_mm_ss(seconds: float) -> str:
    """MM:SS 格式（Markdown 时间戳用）"""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def export_markdown(
    segments: Iterable[dict],
    speaker_aliases: dict,
    title: str,
    duration_sec: float,
    speaker_count: int,
) -> str:
    """Markdown 格式：按说话人分组"""
    lines = [
        f"# {title or '未命名会话'}",
        "",
        f"**Duration**: {_format_mm_ss(duration_sec)}  ",
        f"**Speakers**: {speaker_count}",
        "",
        "---",
        "",
    ]
    # 按说话人分组，保持时间顺序
    groups: dict[str | None, list[dict]] = {}
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        spk = seg.get("speaker_id")
        groups.setdefault(spk, []).append(seg)

    for spk_id, segs in groups.items():
        if spk_id:
            name = speaker_aliases.get(spk_id, spk_id)
            lines.append(f"## {name}")
            lines.append("")
        for seg in segs:
            ts = _format_mm_ss(seg["start_time"])
            lines.append(f"- **[{ts}]** {seg['text']}")
        lines.append("")
    return "\n".join(lines)
