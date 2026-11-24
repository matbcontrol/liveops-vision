"""HTTP-сервис: скриншоты игры на входе, календарь событий на выходе.

    uv run uvicorn liveops_vision.service:app --reload

POST /games/{game}/screenshots  загрузить скриншот (и дату съёмки)
GET  /games/{game}/events       события игры: механика, первый и последний день, сколько экранов
GET  /health

База задаётся DATABASE_URL (Postgres: postgresql+psycopg://...), по умолчанию
локальный SQLite. Почти одинаковый скриншот той же игры второй раз в модель не
уходит: ответ берётся из базы. Читает скриншот каскад: дешёвая модель, а при
низкой уверенности сильная.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Callable

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import preprocess as pp
from .metrics import needs_escalation, norm_name

CHEAP, STRONG = "claude-haiku-5-5", "claude-sonnet-5-5"


class Base(DeclarativeBase):
    pass


class Screenshot(Base):
    __tablename__ = "screenshots"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    game: Mapped[str] = mapped_column(String(200), index=True)
    captured_on: Mapped[date] = mapped_column(Date)
    shape_hash: Mapped[str] = mapped_column(String(80))
    thumb: Mapped[bytes] = mapped_column(LargeBinary)
    duplicate_of: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Reading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screenshot_id: Mapped[str] = mapped_column(ForeignKey("screenshots.id"), index=True)
    model: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)
    cost_usd: Mapped[float] = mapped_column(Float)
    latency_s: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game: Mapped[str] = mapped_column(String(200), index=True)
    key: Mapped[str] = mapped_column(String(300), index=True)
    name: Mapped[str] = mapped_column(String(300))
    mechanics: Mapped[list] = mapped_column(JSON)
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    screens: Mapped[int] = mapped_column(Integer, default=0)


def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///liveops.db")
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


# Reader: (картинка в байтах, модель) -> (разбор, цена, время, модель, ответившая на самом деле)
Reader = Callable[[bytes, str], tuple[dict | None, float, float, str]]


def claude_reader() -> Reader:
    import anthropic

    from .extract import read_screenshot

    client = anthropic.Anthropic(max_retries=4)

    def read(image: bytes, model: str):
        call = read_screenshot(client, model, image, "image/png")
        return call.reading, call.cost_usd, call.latency_s, call.served_by

    return read


def create_app(engine=None, reader: Reader | None = None, max_side: int = 1024) -> FastAPI:
    engine = engine or make_engine()
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    state: dict = {"reader": reader}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        yield

    app = FastAPI(title="LiveOps Vision", lifespan=lifespan)

    def db():
        with SessionLocal() as s:
            yield s

    def get_reader() -> Reader:
        if state["reader"] is None:
            state["reader"] = claude_reader()
        return state["reader"]

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/games/{game}/screenshots")
    async def upload(game: str, file: UploadFile = File(...), captured_on: date | None = Form(None),
                     s: Session = Depends(db), read: Reader = Depends(get_reader)):
        raw = await file.read()
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "файл не читается как картинка")
        day = captured_on or datetime.now(timezone.utc).date()
        sig = pp.signature(img)
        sid = hashlib.sha1(raw).hexdigest()

        # почти такой же скриншот этой игры уже читали: модель не вызываем
        for prev in s.scalars(select(Screenshot).where(Screenshot.game == game, Screenshot.duplicate_of.is_(None))):
            prev_sig = pp.Signature(int(prev.shape_hash), np.frombuffer(prev.thumb, np.int16).reshape(16, 16, 3))
            if pp.similar(sig, prev_sig):
                reading = s.scalars(select(Reading).where(Reading.screenshot_id == prev.id).order_by(Reading.id.desc())).first()
                if not s.get(Screenshot, sid):
                    s.add(Screenshot(id=sid, game=game, captured_on=day, shape_hash=str(sig.shape), thumb=sig.thumb.tobytes(), duplicate_of=prev.id))
                if reading and reading.data.get("is_liveops_event"):
                    _touch_event(s, game, reading.data, day, count=False)
                s.commit()
                return {"screenshot_id": sid, "duplicate_of": prev.id, "model": reading.model if reading else None,
                        "cost_usd": 0.0, "reading": reading.data if reading else None}

        png = pp.encode(pp.fit(img, max_side), ".png")
        data, cost_usd, latency, served = read(png, CHEAP)
        if needs_escalation(data):
            strong, c2, l2, served2 = read(png, STRONG)
            if strong:
                data, served = strong, served2
            cost_usd, latency = cost_usd + c2, latency + l2
        if data is None:
            raise HTTPException(502, "модель не вернула разбор")
        if not s.get(Screenshot, sid):
            s.add(Screenshot(id=sid, game=game, captured_on=day, shape_hash=str(sig.shape), thumb=sig.thumb.tobytes(), duplicate_of=None))
            s.flush()  # SQLite не проверяет внешние ключи и это пропускал, Postgres проверяет
        s.add(Reading(screenshot_id=sid, model=served, data=data, cost_usd=cost_usd, latency_s=latency, created_at=datetime.now(timezone.utc)))
        if data.get("is_liveops_event"):
            _touch_event(s, game, data, day, count=True)
        s.commit()
        return {"screenshot_id": sid, "duplicate_of": None, "model": served, "cost_usd": cost_usd, "reading": data}

    @app.get("/games/{game}/events")
    def events(game: str, s: Session = Depends(db)):
        rows = s.scalars(select(Event).where(Event.game == game).order_by(Event.first_seen)).all()
        return [{"name": e.name, "mechanics": e.mechanics, "first_seen": e.first_seen.isoformat(),
                 "last_seen": e.last_seen.isoformat(), "screens": e.screens} for e in rows]

    return app


def _touch_event(s: Session, game: str, data: dict, day: date, count: bool) -> None:
    name = data.get("event_name") or ""
    key = norm_name(name) or "без названия: " + ",".join(data.get("mechanics") or [])
    ev = s.scalars(select(Event).where(Event.game == game, Event.key == key)).first()
    if ev is None:
        s.add(Event(game=game, key=key, name=name or key, mechanics=data.get("mechanics") or [], first_seen=day, last_seen=day, screens=1))
        return
    ev.first_seen, ev.last_seen = min(ev.first_seen, day), max(ev.last_seen, day)
    if count:
        ev.screens += 1
    if not ev.mechanics and data.get("mechanics"):
        ev.mechanics = data["mechanics"]


app = create_app()
