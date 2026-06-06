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
