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


def load_labels() -> list[dict]:
    return [json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines() if l.strip()]


def run_tag(model: str, max_side: int | None, effort: str) -> str:
    return f"{model}__side{max_side or 'full'}__{effort}"


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
    args = ap.parse_args(argv)
    side = args.max_side or None

    items = [x for x in load_labels() if not x.get("duplicate_of")]
    if args.limit:
        items = items[: args.limit]
    client = anthropic.Anthropic(max_retries=4)
    RUNS.mkdir(exist_ok=True)

    for model in args.models:
        out = RUNS / f"{run_tag(model, side, args.effort)}.jsonl"
        done = set()
        if out.exists():
            done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()}
        todo = [x for x in items if x["id"] not in done]
        print(f"{model}: готово {len(done)}, осталось {len(todo)}", flush=True)

        def work(item: dict) -> dict:
            data, mt, (w, h) = prepare(item, side)
            call = read_screenshot(client, model, data, mt, effort=args.effort)
            return as_row(call, id=item["id"], width=w, height=h, max_side=side, effort=args.effort)

        with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(args.workers) as ex:
            futures = [ex.submit(work, it) for it in todo]
            spent = 0.0
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                spent += row["cost_usd"]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                if i % 20 == 0 or i == len(futures):
                    print(f"  {i}/{len(futures)}, потрачено ${spent:.3f}", flush=True)


if __name__ == "__main__":
    main()
