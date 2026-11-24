import cv2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from liveops_vision import preprocess as pp
from liveops_vision.service import create_app, make_engine

from test_core import card, reading


class FakeReader:
    """Дешёвая модель не уверена на «гонке», сильная уверена; считаем вызовы."""

    def __init__(self):
        self.calls = []

    def __call__(self, image: bytes, model: str):
        self.calls.append(model)
        if "haiku" in model:
            return reading(confidence="low", event_name="Archery Arena"), 0.0002, 0.8, model
        return reading(event_name="Archery Arena", mechanics=["Race", "Leaderboard"]), 0.004, 2.5, model


@pytest.fixture
def client_and_reader():
    engine = make_engine("sqlite://")
    engine.pool = StaticPool(engine.pool._creator)
    fake = FakeReader()
    app = create_app(engine=engine, reader=fake)
    with TestClient(app) as c:
        yield c, fake


def png(img):
    return ("shot.png", pp.encode(img), "image/png")


def test_upload_cascade_and_calendar(client_and_reader):
    c, fake = client_and_reader
    r = c.post("/games/Royal Match/screenshots", files={"file": png(card())}, data={"captured_on": "2026-11-20"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert fake.calls == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert body["reading"]["mechanics"][0] == "Race"
    assert body["cost_usd"] == pytest.approx(0.0042)

    # тот же экран, снятый позже и в другом размере: модель не вызывается, событие продлевается
    r2 = c.post("/games/Royal Match/screenshots", files={"file": png(cv2.resize(card(), (450, 800)))}, data={"captured_on": "2026-11-23"})
    assert r2.json()["duplicate_of"] == body["screenshot_id"]
    assert r2.json()["cost_usd"] == 0.0
    assert len(fake.calls) == 2

    ev = c.get("/games/Royal Match/events").json()
    assert ev == [{"name": "Archery Arena", "mechanics": ["Race", "Leaderboard"], "first_seen": "2026-11-20",
                   "last_seen": "2026-11-23", "screens": 1}]


def test_other_game_is_separate(client_and_reader):
    c, fake = client_and_reader
    c.post("/games/A/screenshots", files={"file": png(card())})
    c.post("/games/B/screenshots", files={"file": png(card())})
    assert len(fake.calls) == 4
    assert c.get("/games/C/events").json() == []


def test_same_flow_on_postgres(tmp_path):
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(str(tmp_path / "pg"), cleanup_mode="stop")
    url = srv.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    fake = FakeReader()
    with TestClient(create_app(engine=make_engine(url), reader=fake)) as c:
        c.post("/games/Royal Match/screenshots", files={"file": png(card())}, data={"captured_on": "2026-11-20"})
        r2 = c.post("/games/Royal Match/screenshots", files={"file": png(cv2.resize(card(), (450, 800)))}, data={"captured_on": "2026-11-23"})
        assert r2.json()["cost_usd"] == 0.0
        ev = c.get("/games/Royal Match/events").json()
    assert ev[0]["last_seen"] == "2026-11-23" and len(fake.calls) == 2


def test_not_an_image(client_and_reader):
    c, _ = client_and_reader
    r = c.post("/games/A/screenshots", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 400
