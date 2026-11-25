"""Метрики: обнаружение события, название, механика, цена, время. Без сети."""

from __future__ import annotations

import random
import re
import statistics
import unicodedata
from difflib import SequenceMatcher

STOP = {"event", "events", "the", "a", "of", "and"}

# Заголовки служебных экранов события: на них нет названия самого события
# (Township «Golden Ticket», Candy Crush «How it works»). Если модель честно
# прочитала такой заголовок, скриншот не участвует в метрике названия.
GENERIC_TITLES = {
    "golden ticket", "how does it work", "how it works", "how to play", "event center", "personal goal",
    "global goal", "congratulations", "contest", "your messages", "level up", "reward", "rewards",
    "event calendar", "info", "instructions", "how do i participate", "tasks", "perks", "season points",
    "how to get season points", "grand prize", "leaderboard", "ranking",
}


def is_generic_title(s: str | None) -> bool:
    n = norm_name(s)
    return bool(n) and (n in GENERIC_TITLES or any(n.startswith(g + " ") for g in ("how does it work", "how it works")))


def norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)  # эмодзи, пунктуация
    words = [w for w in s.split() if w not in STOP]
    return " ".join(words)


def name_match(pred: str | None, gt: str | None, threshold: float = 0.8) -> bool:
    a, b = norm_name(pred), norm_name(gt)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def binary(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs: (истина, ответ модели)."""
    tp = sum(1 for t, p in pairs if t and p)
    fp = sum(1 for t, p in pairs if not t and p)
    fn = sum(1 for t, p in pairs if t and not p)
    tn = sum(1 for t, p in pairs if not t and not p)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1,
            "accuracy": (tp + tn) / len(pairs) if pairs else 0.0}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95 % интервал для среднего (доля верных ответов и т. п.)."""
    if not values:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(statistics.fmean(rnd.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def score(rows: list[dict], labels: dict[str, dict]) -> dict:
    """rows: ответы одной конфигурации; labels: разметка по id картинки."""
    ok = [r for r in rows if r.get("reading") and r["id"] in labels]
    det = [(labels[r["id"]]["is_event"], bool(r["reading"]["is_liveops_event"])) for r in ok]
    events = [r for r in ok if labels[r["id"]]["is_event"]]
    # название меряется там, где страница вики описывает одно событие и её заголовок можно считать эталоном
    named_all = [r for r in events if labels[r["id"]].get("name_reliable", True) and labels[r["id"]].get("event_name")]
    named = [r for r in named_all if not is_generic_title(r["reading"]["event_name"])]
    name_hits = [1.0 if name_match(r["reading"]["event_name"], labels[r["id"]]["event_name"]) else 0.0 for r in named]
    returned = [r for r in named if r["reading"]["event_name"]]
    name_precision = statistics.fmean([1.0 if name_match(r["reading"]["event_name"], labels[r["id"]]["event_name"]) else 0.0 for r in returned]) if returned else 0.0
    with_mech = [r for r in events if labels[r["id"]].get("mechanic")]
    mech_main = [1.0 if (r["reading"]["mechanics"] or [None])[0] in labels[r["id"]]["mechanics_ok"] else 0.0 for r in with_mech]
    mech_any = [1.0 if set(r["reading"]["mechanics"]) & set(labels[r["id"]]["mechanics_ok"]) else 0.0 for r in with_mech]
    costs = [r["cost_usd"] for r in rows if r.get("reading")]
    lat = [r["latency_s"] for r in rows if r.get("reading")]
    return {
        "n": len(rows), "answered": len(ok), "errors": sum(1 for r in rows if r.get("error")),
        "fallback_served": sum(1 for r in rows if r.get("served_by") and r["served_by"] != r["model"]),
        "detection": binary(det),
        "detection_acc_ci": bootstrap_ci([1.0 if t == p else 0.0 for t, p in det]),
        "name_acc": statistics.fmean(name_hits) if name_hits else 0.0, "name_n": len(name_hits),
        "name_returned_rate": len(returned) / len(named) if named else 0.0, "name_precision": name_precision,
        "name_generic_screens": len(named_all) - len(named),
        "name_ci": bootstrap_ci(name_hits),
        "mechanic_main_acc": statistics.fmean(mech_main) if mech_main else 0.0,
        "mechanic_any_acc": statistics.fmean(mech_any) if mech_any else 0.0, "mechanic_n": len(mech_main),
        "mechanic_ci": bootstrap_ci(mech_main),
        "cost_per_image": statistics.fmean(costs) if costs else 0.0,
        "cost_per_1000": 1000 * statistics.fmean(costs) if costs else 0.0,
        "latency_p50": percentile(lat, 0.5), "latency_p90": percentile(lat, 0.9),
        "input_tokens_mean": statistics.fmean([r["input_tokens"] for r in ok]) if ok else 0.0,
        "output_tokens_mean": statistics.fmean([r["output_tokens"] for r in ok]) if ok else 0.0,
    }


def needs_escalation(reading: dict | None) -> bool:
    """Правило каскада: дешёвая модель не уверена или механика не определилась."""
    if not reading:
        return True
    if reading["confidence"] != "high":
        return True
    if reading["is_liveops_event"] and (not reading["mechanics"] or reading["mechanics"][0] == "Other"):
        return True
    return False


def main_mechanic(reading: dict | None) -> str | None:
    if not reading or not reading["is_liveops_event"]:
        return None
    return (reading["mechanics"] or ["Other"])[0]


def disagree(a: dict | None, b: dict | None) -> bool:
    """Две дешёвые модели расходятся: одна видит событие, другая нет, или главные механики разные."""
    if not a or not b:
        return True
    return a["is_liveops_event"] != b["is_liveops_event"] or main_mechanic(a) != main_mechanic(b)


def calibration(rows: list[dict], labels: dict[str, dict]) -> dict[str, dict]:
    """Насколько самооценка модели совпадает с правотой: доля верных ответов по уровню уверенности."""
    out: dict[str, dict] = {}
    for r in rows:
        x, lab = r.get("reading"), labels.get(r["id"])
        if not x or not lab:
            continue
        ok = lab["is_event"] == x["is_liveops_event"]
        if ok and lab["is_event"] and lab.get("mechanic"):
            ok = main_mechanic(x) in lab["mechanics_ok"]
        c = out.setdefault(x["confidence"], {"n": 0, "right": 0})
        c["n"] += 1
        c["right"] += ok
    for c in out.values():
        c["accuracy"] = c["right"] / c["n"]
    return out


def cascade(cheap: list[dict], strong: list[dict], escalate=None) -> list[dict]:
    """Каскад из готовых прогонов: ответ дешёвой модели или, по правилу, сильной; цена складывается.

    escalate: функция строки дешёвой модели -> bool; по умолчанию самооценка (needs_escalation).
    Если сильного ответа для скриншота нет, остаётся ответ дешёвой модели.
    """
    escalate = escalate or (lambda r: needs_escalation(r.get("reading")))
    by_id = {r["id"]: r for r in strong}
    out = []
    for r in cheap:
        s = by_id.get(r["id"])
        if escalate(r) and s and s.get("reading"):
            out.append({**s, "cost_usd": r["cost_usd"] + s["cost_usd"], "latency_s": r["latency_s"] + s["latency_s"],
                        "input_tokens": r["input_tokens"] + s["input_tokens"], "output_tokens": r["output_tokens"] + s["output_tokens"],
                        "escalated": True})
        else:
            out.append({**r, "escalated": False})
    return out
