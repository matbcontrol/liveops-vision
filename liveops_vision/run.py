"""Прогон набора через модели с сохранением каждого ответа.

    uv run python -m liveops_vision.run --models claude-haiku-5-5 claude-sonnet-5-5 --max-side 1024

Ответы пишутся в runs/<модель>__side<N>__<effort>.jsonl построчно. Повторный
запуск пропускает уже готовые картинки, так что оборванный прогон не стоит
денег второй раз.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

from . import preprocess as pp
from .extract import as_row, read_screenshot

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "labels.jsonl"
RUNS = ROOT / "runs"


def load_env() -> None:
    """Ключи из .env в корне проекта (файл в .gitignore), если их нет в окружении."""
    import os

    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def make_reader(model: str, prompt: str = "v1"):
    """Функция (картинка, effort) -> Call для Claude или Gemini по имени модели."""
    import os

    if model.startswith("gemini"):
        from google import genai
        from google.genai import types

        from .gemini import read_screenshot as gem_read

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=90_000))
        return lambda data, mt, effort: gem_read(client, model, data, mt, effort=effort, prompt=prompt)
    client = anthropic.Anthropic(max_retries=4)
    return lambda data, mt, effort: read_screenshot(client, model, data, mt, effort=effort, prompt=prompt)


def load_labels() -> list[dict]:
    return [json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines() if l.strip()]


def run_tag(model: str, max_side: int | None, effort: str, prompt: str = "v1") -> str:
    return f"{model}__side{max_side or 'full'}__{effort}" + ("" if prompt == "v1" else f"__{prompt}")


def prepare(item: dict, max_side: int | None) -> tuple[bytes, str, tuple[int, int]]:
    img = pp.fit(pp.load(ROOT / item["path"]), max_side)
    h, w = img.shape[:2]
    return pp.encode(img, ".png"), "image/png", (w, h)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["claude-haiku-5-5"])
    ap.add_argument("--max-side", type=int, default=1024, help="0 = без уменьшения")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--prompt", default="v1", choices=["v1", "v2"])
    ap.add_argument("--only", default="", help="escalated:<прогон> или disagree:<прогон A>,<прогон B>: только скриншоты, которые каскад отдаст сильной модели")
    args = ap.parse_args(argv)
    side = args.max_side or None

    load_env()
    items = [x for x in load_labels() if not x.get("duplicate_of")]
    if args.only:
        from .metrics import disagree, needs_escalation

        def rows_of(stem: str) -> dict[str, dict]:
            return {r["id"]: r for r in map(json.loads, (RUNS / f"{stem}.jsonl").read_text(encoding="utf-8").splitlines())}

        kind, _, spec = args.only.partition(":")
        if kind == "escalated":
            src = rows_of(spec)
            keep = {i for i, r in src.items() if needs_escalation(r.get("reading"))}
        elif kind == "disagree":
            a, b = (rows_of(s) for s in spec.split(","))
            keep = {i for i in a if disagree(a[i].get("reading"), b.get(i, {}).get("reading"))}
        else:
            raise SystemExit(f"неизвестный фильтр {args.only}")
        items = [x for x in items if x["id"] in keep]
        print(f"фильтр {args.only}: {len(items)} скриншотов", flush=True)
    if args.limit:
        items = items[: args.limit]
    RUNS.mkdir(exist_ok=True)

    for model in args.models:
        reader = make_reader(model, args.prompt)
        out = RUNS / f"{run_tag(model, side, args.effort, args.prompt)}.jsonl"
        done = set()
        if out.exists():
            done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()}
        todo = [x for x in items if x["id"] not in done]
        print(f"{model}: готово {len(done)}, осталось {len(todo)}", flush=True)

        def work(item: dict) -> dict:
            data, mt, (w, h) = prepare(item, side)
            call = reader(data, mt, args.effort)
            return as_row(call, id=item["id"], width=w, height=h, max_side=side, effort=args.effort, prompt=args.prompt)

        with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(args.workers) as ex:
            futures = [ex.submit(work, it) for it in todo]
            spent = 0.0
            for i, fut in enumerate(as_completed(futures), 1):
                try:
                    row = fut.result()
                except Exception as e:  # одна сломанная картинка не должна ронять прогон
                    print(f"  ошибка: {type(e).__name__}: {e}", flush=True)
                    continue
                spent += row["cost_usd"]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                if i % 20 == 0 or i == len(futures):
                    print(f"  {i}/{len(futures)}, потрачено ${spent:.3f}", flush=True)


if __name__ == "__main__":
    main()
