"""Shared display semantics for machine and user-confirmed speaker identities."""
from __future__ import annotations

TRUSTED_IDENTITY_STATUSES = frozenset({"auto_matched", "confirmed"})


def speaker_display_name(segment: dict, *, unknown: str = "未识别") -> str:
    """Return a real name only when its identity provenance is trusted."""
    status = segment.get("identity_status")
    trusted = status in TRUSTED_IDENTITY_STATUSES or (
        status is None and bool(segment.get("manually_confirmed"))
    )
    if trusted and segment.get("person_name"):
        return str(segment["person_name"])
    return str(
        segment.get("speaker_label")
        or segment.get("speaker_id")
        or unknown
    )
