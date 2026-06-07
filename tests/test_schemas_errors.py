from app.schemas.errors import ErrorResponse, error_response


def test_error_response_required_fields():
    r = ErrorResponse(code="AUDIO_TOO_LONG", message="音频过长")
    assert r.code == "AUDIO_TOO_LONG"
    assert r.message == "音频过长"
    assert r.detail is None
    assert r.retry_after is None


def test_error_response_optional_fields():
    r = ErrorResponse(
        code="LLM_UNAVAILABLE",
        message="LLM 不可用",
        detail="connection refused to 127.0.0.1:11434",
        retry_after=60,
    )
    assert r.retry_after == 60


def test_error_response_helper():
    r = error_response("X", "msg", retry_after=10)
    assert isinstance(r, dict)
    assert r["code"] == "X"
    assert r["retry_after"] == 10
