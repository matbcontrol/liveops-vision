from types import SimpleNamespace

import pytest
from google.genai import errors

from liveops_vision import gemini
from liveops_vision import preprocess as pp
from liveops_vision.schema import ScreenshotReading

from test_core import card, reading


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def response(parsed=None, text=None, tin=1100, tout=150, thoughts=50):
    usage = SimpleNamespace(prompt_token_count=tin, candidates_token_count=tout, thoughts_token_count=thoughts)
    return SimpleNamespace(parsed=parsed, text=text, usage_metadata=usage, model_version="gemini-3.6-flash-001",
                           candidates=[SimpleNamespace(finish_reason="STOP")])


def test_parsed_answer_and_paid_tier_cost():
    fake = FakeModels([response(parsed=ScreenshotReading(**reading()))])
    call = gemini.read_screenshot(SimpleNamespace(models=fake), "gemini-3.6-flash", pp.encode(card()))
    assert call.error is None and call.reading["mechanics"] == ["Race"]
    assert call.output_tokens == 200  # ответ + размышления
    assert call.cost_usd == pytest.approx((1100 * 0.75 + 200 * 3.75) / 1e6)
    cfg = fake.calls[0]["config"]
    assert cfg.response_schema is ScreenshotReading and cfg.response_mime_type == "application/json"


def test_text_fallback_when_parsed_missing():
    text = ScreenshotReading(**reading(event_name="Hidden Temple", mechanics=["Digging"])).model_dump_json()
    fake = FakeModels([response(parsed=None, text=text)])
    call = gemini.read_screenshot(SimpleNamespace(models=fake), "gemini-3.5-flash-lite", pp.encode(card()))
    assert call.reading["event_name"] == "Hidden Temple"


def test_retries_on_overload_then_succeeds(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    busy = errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
    fake = FakeModels([busy, busy, response(parsed=ScreenshotReading(**reading()))])
    call = gemini.read_screenshot(SimpleNamespace(models=fake), "gemini-3.6-flash", pp.encode(card()))
    assert call.error is None and len(fake.calls) == 3


def test_network_timeout_is_retried(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    fake = FakeModels([TimeoutError("read timed out"), response(parsed=ScreenshotReading(**reading()))])
    call = gemini.read_screenshot(SimpleNamespace(models=fake), "gemini-3.6-flash", pp.encode(card()))
    assert call.error is None and len(fake.calls) == 2


def test_client_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}})
    fake = FakeModels([bad])
    call = gemini.read_screenshot(SimpleNamespace(models=fake), "gemini-3.6-flash", pp.encode(card()))
    assert call.reading is None and call.error.startswith("400") and len(fake.calls) == 1
