"""Один скриншот → разбор по схеме через Claude API.

Модель видит только картинку и описание классификации. Ответ ограничен схемой
ScreenshotReading (structured outputs), поэтому всегда разбирается. Для каждого
вызова записываются токены, цена и время.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import anthropic

from .schema import ScreenshotReading
from .taxonomy import MECHANICS, MOTIVATIONS, SCREEN_TYPES

# $ за 1 млн токенов: (вход, выход, чтение из кэша). Источник: прайс Anthropic, ноябрь 2026.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}
# у Haiku 5.5 нет серверного запасного маршрута при отказе
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}


# Версия 2 появилась после разбора ошибок версии 1: модель принимала постоянные
# разделы игры (музей с коллекцией, аэропорт, заводы, ежедневный бонус) за события.
PERMANENT_RULE = """

Permanent game features are not LiveOps events even when they look like progress screens: collections and museums that are always available, production buildings and orders (factories, airport, train, port), the shop, daily login bonuses, profile and settings, level start and level end pop-ups. Mark a screen as an event only when it shows a limited-time signal: a countdown timer or end date, an event title or banner, event points or a season/event pass. A collection screen with no timer and no event branding is a permanent feature."""


def system_prompt(version: str = "v1") -> str:
    return _base_prompt() + (PERMANENT_RULE if version == "v2" else "")


def _base_prompt() -> str:
    mech = "\n".join(f"- {k}: {v}" for k, v in MECHANICS.items())
    screens = "\n".join(f"- {k}: {v}" for k, v in SCREEN_TYPES.items())
    return f"""You read screenshots of mobile games for a market intelligence product that tracks LiveOps: limited-time events, their mechanics and how games run them.

For each screenshot decide whether a LiveOps event screen is the main content. A home screen or an ordinary level that only shows small event icons on the side is not an event screen. Read the event title exactly as written on screen; if no title is visible, return null rather than guessing a name.

Mechanics (use the main one first; several are allowed when the screen clearly shows them):
{mech}

Motivations: {", ".join(MOTIVATIONS)}.

Screen types:
{screens}

Rely only on what is visible. The game may be in any language; keep the title in the original language. Use confidence "low" when the screen is ambiguous."""


@dataclass
class Call:
    model: str
    served_by: str
    reading: dict | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    latency_s: float
    cost_usd: float


def cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    pin, pout, pcache = PRICES[model]
    return (input_tokens * pin + output_tokens * pout + cache_read * pcache) / 1_000_000


def read_screenshot(client: anthropic.Anthropic, model: str, image: bytes, media_type: str = "image/png",
                    effort: str = "low", hint: str | None = None, prompt: str = "v1") -> Call:
    import base64

    content: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(image).decode()}},
        {"type": "text", "text": hint or "Read this screenshot."},
    ]
    kwargs: dict = dict(
        model=model,
        max_tokens=4000,
        system=[{"type": "text", "text": system_prompt(prompt), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=ScreenshotReading,
        output_config={"effort": effort},
    )
    if model in FALLBACK_MODELS:
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    t0 = time.perf_counter()
    try:
        resp = client.beta.messages.parse(**kwargs)
    except anthropic.APIStatusError as e:
        return Call(model, model, None, f"{e.status_code}: {e.message}", 0, 0, 0, time.perf_counter() - t0, 0.0)
    except anthropic.APIConnectionError as e:
        return Call(model, model, None, f"connection: {e}", 0, 0, 0, time.perf_counter() - t0, 0.0)
    latency = time.perf_counter() - t0
    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    served = getattr(resp, "model", model) or model
    # запись в кэш стоит 1,25 цены входа, она входит в input для оценки цены
    billed_input = u.input_tokens + round(cache_write * 1.25)
    price_model = served if served in PRICES else model
    if resp.stop_reason == "refusal":
        return Call(model, served, None, "refusal", u.input_tokens, u.output_tokens, cache_read, latency,
                    cost(price_model, billed_input, u.output_tokens, cache_read))
    parsed = resp.parsed_output
    return Call(model, served, parsed.model_dump() if parsed else None, None if parsed else f"no parse ({resp.stop_reason})",
                u.input_tokens + cache_write, u.output_tokens, cache_read, latency,
                cost(price_model, billed_input, u.output_tokens, cache_read))


def as_row(call: Call, **extra) -> dict:
    return {**extra, **asdict(call)}
