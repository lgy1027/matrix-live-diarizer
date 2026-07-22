"""Conservative matching of meeting embeddings to user-confirmed people."""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np

# "强样本"判定门槛:质量分与有效语音时长同时达标才算一个可用于自动匹配的样本。
# people.py 注册声样后用同一对常量算 auto_match_eligible,与下方 strong_sample 统计保持一致。
STRONG_SAMPLE_MIN_QUALITY = 0.6
STRONG_SAMPLE_MIN_SPEECH_SEC = 3.0


@dataclass(frozen=True)
class IdentityMatchDecision:
    person_id: str | None
    score: float
    status: str


def match_person(
    embedding: np.ndarray,
    samples: list[dict],
    *,
    threshold: float = 0.78,
    margin: float = 0.03,
    model_id: str | None = None,
) -> tuple[str | None, float]:
    """Return an identity *suggestion*, never an automatic confirmation.

    Only samples carrying the exact same embedding compatibility identity are
    considered. The caller must persist the result as an unconfirmed suggestion
    and require a person to confirm it.
    """
    current = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(current))
    if not current.size or norm <= 1e-8:
        return None, 0.0
    if model_id is None:
        candidate_model_ids = {
            str(sample.get("model_id"))
            for sample in samples
            if sample.get("model_id")
        }
        if len(candidate_model_ids) != 1:
            return None, 0.0
        model_id = candidate_model_ids.pop()
    scores: dict[str, list[float]] = {}
    for sample in samples:
        sample_model_id = sample.get("model_id")
        if not sample_model_id or sample_model_id != model_id:
            continue
        raw = sample.get("embedding")
        if not raw:
            continue
        known = np.frombuffer(raw, dtype=np.float32)
        if known.size != current.size:
            continue
        denominator = norm * float(np.linalg.norm(known))
        if denominator <= 1e-8:
            continue
        score = float(np.dot(current, known) / denominator)
        scores.setdefault(sample["person_id"], []).append(score)
    if not scores:
        return None, 0.0
    ranked = sorted(
        ((person_id, max(values)) for person_id, values in scores.items()),
        key=lambda item: item[1], reverse=True,
    )
    person_id, score = ranked[0]
    # Require both absolute confidence and separation from the runner-up.
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
    if score < threshold or score - runner_up < margin:
        return None, score
    return person_id, score


def classify_person_match(
    embedding: np.ndarray,
    samples: list[dict],
    *,
    model_id: str,
    speech_duration: float,
    suggestion_threshold: float,
    suggestion_margin: float,
    auto_threshold: float,
    auto_margin: float,
    min_auto_samples: int = 2,
    min_auto_speech_sec: float = 5.0,
) -> IdentityMatchDecision:
    """Classify a compatible voice match without treating weak evidence as identity.

    A suggestion needs one accepted meeting-level candidate. Automatic display
    additionally needs a stricter candidate/margin, enough aggregate speech,
    and multiple independently strong enrollment samples from that same person.
    """
    person_id, score = match_person(
        embedding,
        samples,
        threshold=suggestion_threshold,
        margin=suggestion_margin,
        model_id=model_id,
    )
    if person_id is None:
        return IdentityMatchDecision(None, score, "anonymous")

    auto_person_id, _ = match_person(
        embedding,
        samples,
        threshold=auto_threshold,
        margin=auto_margin,
        model_id=model_id,
    )
    current = np.asarray(embedding, dtype=np.float32).reshape(-1)
    current_norm = float(np.linalg.norm(current))
    strong_sample_count = 0
    if auto_person_id == person_id and current_norm > 1e-8:
        for sample in samples:
            if (
                sample.get("person_id") != person_id
                or sample.get("model_id") != model_id
                or not sample.get("embedding")
                or float(sample.get("quality_score") or 0.0) < STRONG_SAMPLE_MIN_QUALITY
                or float(sample.get("effective_speech_sec") or 0.0) < STRONG_SAMPLE_MIN_SPEECH_SEC
            ):
                continue
            known = np.frombuffer(sample["embedding"], dtype=np.float32)
            if known.size != current.size:
                continue
            denominator = current_norm * float(np.linalg.norm(known))
            if denominator <= 1e-8:
                continue
            if float(np.dot(current, known) / denominator) >= auto_threshold:
                strong_sample_count += 1

    if (
        auto_person_id == person_id
        and speech_duration >= min_auto_speech_sec
        and strong_sample_count >= min_auto_samples
    ):
        return IdentityMatchDecision(person_id, score, "auto_matched")
    return IdentityMatchDecision(person_id, score, "suggested")
