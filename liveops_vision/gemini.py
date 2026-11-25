"""Тот же разбор скриншота через Gemini API (google-genai).

Схема ответа, системный промпт и запись цены те же, что у Claude, так что
модели сравниваются на одинаковой задаче. Бесплатный уровень Gemini режет
частоту запросов: на 429 вызов ждёт столько, сколько просит API, и повторяет.
"""

from __future__ import annotations

import random
import re
import time

from google import genai
from google.genai import errors, types

from .extract import Call, system_prompt
from .schema import ScreenshotReading

# $ за 1 млн токенов платного уровня (вход, выход вместе с размышлениями), ai.google.dev/pricing, ноябрь 2026
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
}


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


def _retry_delay(err: Exception, attempt: int) -> float:
    m = re.search(r"retry(?:Delay| in)[\"':\s]*([\d.]+)s", str(err))
    base = float(m.group(1)) if m else 2 ** attempt * 5
    return min(120.0, base + random.uniform(0, 2))


def read_screenshot(client: genai.Client, model: str, image: bytes, media_type: str = "image/png",
                    effort: str = "low", max_attempts: int = 8, prompt: str = "v1") -> Call:
    config = types.GenerateContentConfig(
        system_instruction=system_prompt(prompt),
        response_mime_type="application/json",
        response_schema=ScreenshotReading,
        thinking_config=types.ThinkingConfig(thinking_level=effort) if effort and effort != "none" else None,
        max_output_tokens=4000,
    )
    contents = [types.Part.from_bytes(data=image, mime_type=media_type), "Read this screenshot."]
    t0 = time.perf_counter()
    last = ""
    for attempt in range(max_attempts):
        t_try = time.perf_counter()
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            last = f"{e.code}: {str(e)[:200]}"
            if e.code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                time.sleep(_retry_delay(e, attempt))
                continue
            return Call(model, model, None, last, 0, 0, 0, time.perf_counter() - t0, 0.0)
        except Exception as e:  # обрыв сети, таймаут чтения: SDK отдаёт их не как APIError
            last = f"network: {type(e).__name__}"
            if attempt < max_attempts - 1:
                time.sleep(_retry_delay(e, attempt))
                continue
            return Call(model, model, None, last, 0, 0, 0, time.perf_counter() - t0, 0.0)
        latency = time.perf_counter() - t_try  # время удачного запроса, без ожидания лимитов
        u = resp.usage_metadata
        tin = (u.prompt_token_count or 0) if u else 0
        tout = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        parsed = resp.parsed if isinstance(resp.parsed, ScreenshotReading) else None
        if parsed is None and resp.text:
            try:
                parsed = ScreenshotReading.model_validate_json(resp.text)
            except ValueError:
                parsed = None
        reason = resp.candidates[0].finish_reason if resp.candidates else None
        return Call(model, getattr(resp, "model_version", None) or model, parsed.model_dump() if parsed else None,
                    None if parsed else f"no parse ({reason})", tin, tout, 0, latency, cost(model, tin, tout))
    return Call(model, model, None, last or "retries exhausted", 0, 0, 0, time.perf_counter() - t0, 0.0)
