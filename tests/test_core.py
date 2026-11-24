from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from liveops_vision import metrics as m
from liveops_vision import preprocess as pp
from liveops_vision.extract import cost, read_screenshot, system_prompt
from liveops_vision.schema import ScreenshotReading


def card(color=(40, 120, 200), text="RACE", size=(900, 1600)):
    w, h = size
    img = np.full((h, w, 3), 30, np.uint8)
    cv2.rectangle(img, (80, 300), (w - 80, h - 300), color, -1)
    cv2.putText(img, text, (150, 500), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8)
    return img


def test_dhash_same_screen_after_resize_and_jpeg():
    a = card()
    b = cv2.imdecode(np.frombuffer(pp.encode(cv2.resize(a, (450, 800)), ".jpg"), np.uint8), cv2.IMREAD_COLOR)
    assert pp.hamming(pp.dhash(a), pp.dhash(b)) <= 10


def test_same_template_different_event_is_not_duplicate():
    # одна раскладка окна, другое событие: хэш формы почти совпадает, цвет нет
    a, b = card(), card(color=(200, 40, 40), text="ALBUM")
    assert pp.hamming(pp.dhash(a), pp.dhash(b)) <= 10
    assert not pp.similar(pp.signature(a), pp.signature(b))


def test_dedupe_keeps_first():
    sigs = {"a": pp.signature(card()), "b": pp.signature(cv2.resize(card(), (300, 533))),
            "c": pp.signature(card(text="DIG", color=(0, 200, 0)))}
    assert pp.dedupe(sigs) == {"a": "a", "b": "a", "c": "c"}


def test_fit_only_shrinks():
    assert pp.fit(card(), 1024).shape[:2] == (1024, 576)
    small = card(size=(300, 500))
    assert pp.fit(small, 1024) is small


def test_image_token_estimate_scales_with_pixels():
    assert pp.estimate_image_tokens(1280, 720) == pytest.approx(1176, abs=2)
    assert pp.estimate_image_tokens(2560, 1440) == pytest.approx(4 * pp.estimate_image_tokens(1280, 720), abs=4)


def test_changed_regions_finds_new_banner():
    before = card()
    after = before.copy()
    cv2.rectangle(after, (100, 1350), (500, 1500), (0, 220, 255), -1)
    boxes = pp.changed_regions(before, after)
    assert boxes, "изменение не найдено"
    x, y, w, h = boxes[0]
    assert x <= 100 and y <= 1350 and x + w >= 500 and y + h >= 1500


def test_keyframes_skip_static_video(tmp_path):
    path = tmp_path / "v.avi"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (360, 640))
    for _ in range(20):
        vw.write(cv2.resize(card(), (360, 640)))
    for _ in range(20):
        vw.write(cv2.resize(card(color=(0, 0, 220), text="WIN"), (360, 640)))
    vw.release()
    frames = pp.keyframes(path, every_s=0.5)
    assert len(frames) == 2
    assert frames[1].seconds >= 1.9


def test_name_match():
    assert m.name_match("🏹 Archery Arena", "Archery Arena")
    assert m.name_match("CANDY DAY", "Candy Day Event")
    assert m.name_match("Sweet Streak!", "Sweet Streak")
    assert not m.name_match("Treasure Hunt", "Archery Arena")
    assert not m.name_match(None, "Archery Arena")


def test_generic_titles_are_skipped_in_name_metric():
    assert m.is_generic_title("GOLDEN TICKET") and m.is_generic_title("How does it work?")
    assert not m.is_generic_title("Golden Gala")
    labels = {"a": {"is_event": True, "event_name": "Ancient World", "name_reliable": True, "mechanic": None, "mechanics_ok": []},
              "b": {"is_event": True, "event_name": "Ancient World", "name_reliable": True, "mechanic": None, "mechanics_ok": []}}
    rows = [{"id": "a", "model": "h", "reading": reading(event_name="Golden Ticket"), "cost_usd": 0, "latency_s": 1, "input_tokens": 1, "output_tokens": 1},
            {"id": "b", "model": "h", "reading": reading(event_name="ANCIENT WORLD"), "cost_usd": 0, "latency_s": 1, "input_tokens": 1, "output_tokens": 1}]
    s = m.score(rows, labels)
    assert s["name_n"] == 1 and s["name_acc"] == 1.0 and s["name_generic_screens"] == 1


def test_binary_metrics():
    r = m.binary([(True, True), (True, False), (False, True), (False, False)])
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 1)
    assert r["precision"] == r["recall"] == r["f1"] == 0.5


def reading(**kw):
    base = dict(screen_type="event_intro", is_liveops_event=True, event_name="Archery Arena", mechanics=["Race"],
                motivations=["Competitive"], has_leaderboard=True, time_left=None, rewards_visible=[],
                confidence="high", evidence="title and race track")
    base.update(kw)
    return ScreenshotReading(**base).model_dump()


def test_score_and_cascade():
    labels = {
        "a": {"is_event": True, "event_name": "Archery Arena", "mechanic": "Race", "mechanics_ok": ["Race"]},
        "b": {"is_event": False, "event_name": None, "mechanic": None, "mechanics_ok": []},
    }
    cheap = [
        {"id": "a", "model": "h", "served_by": "h", "reading": reading(confidence="low", mechanics=["Other"]), "cost_usd": 0.001, "latency_s": 1, "input_tokens": 1000, "output_tokens": 100},
        {"id": "b", "model": "h", "served_by": "h", "reading": reading(is_liveops_event=False, mechanics=[], event_name=None, screen_type="regular_gameplay"), "cost_usd": 0.001, "latency_s": 1, "input_tokens": 1000, "output_tokens": 100},
    ]
    strong = [
        {"id": "a", "model": "s", "served_by": "s", "reading": reading(), "cost_usd": 0.01, "latency_s": 3, "input_tokens": 1000, "output_tokens": 200},
        {"id": "b", "model": "s", "served_by": "s", "reading": reading(is_liveops_event=False, mechanics=[], event_name=None), "cost_usd": 0.01, "latency_s": 3, "input_tokens": 1000, "output_tokens": 200},
    ]
    s_cheap = m.score(cheap, labels)
    assert s_cheap["detection"]["f1"] == 1.0 and s_cheap["mechanic_main_acc"] == 0.0
    mixed = m.cascade(cheap, strong)
    assert [r["escalated"] for r in mixed] == [True, False]
    s_mixed = m.score(mixed, labels)
    assert s_mixed["mechanic_main_acc"] == 1.0
    assert s_mixed["cost_per_image"] == pytest.approx((0.011 + 0.001) / 2)


def test_cost():
    assert cost("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert cost("claude-sonnet-5-5", 1000, 1000) == pytest.approx(0.012)


def test_system_prompt_lists_appmagic_mechanics():
    p = system_prompt()
    for name in ["Race", "Album", "Win Streak", "Lava Quest", "Digging", "Core Duplicates"]:
        assert name in p


class FakeMessages:
    def __init__(self, resp):
        self.resp, self.kwargs = resp, None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


def fake_client(resp):
    msgs = FakeMessages(resp)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_read_screenshot_request_and_cost():
    parsed = ScreenshotReading(**reading())
    usage = SimpleNamespace(input_tokens=1500, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    client, msgs = fake_client(SimpleNamespace(usage=usage, stop_reason="end_turn", parsed_output=parsed, model="claude-sonnet-5-5"))
    call = read_screenshot(client, "claude-sonnet-5-5", pp.encode(card()), "image/png")
    assert call.error is None and call.reading["event_name"] == "Archery Arena"
    assert call.cost_usd == pytest.approx(cost("claude-sonnet-5-5", 1500, 200))
    k = msgs.kwargs
    assert k["output_format"] is ScreenshotReading
    assert k["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in k["betas"]
    assert k["messages"][0]["content"][0]["type"] == "image"


def test_haiku_has_no_fallback_and_refusal_is_error():
    usage = SimpleNamespace(input_tokens=1500, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    client, msgs = fake_client(SimpleNamespace(usage=usage, stop_reason="refusal", parsed_output=None, model="claude-haiku-5-5"))
    call = read_screenshot(client, "claude-haiku-5-5", pp.encode(card()), "image/png")
    assert "fallbacks" not in msgs.kwargs
    assert call.reading is None and call.error == "refusal"
