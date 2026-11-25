"""Сводка по всем прогонам: results/summary.json и results/results.md.

    uv run python -m liveops_vision.report
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .metrics import cascade, needs_escalation, score

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def ci(c: tuple[float, float]) -> str:
    return f"{100 * c[0]:.0f}–{100 * c[1]:.0f}"


def main() -> None:
    labels_list = load(ROOT / "data" / "labels.jsonl")
    labels = {x["id"]: x for x in labels_list if not x.get("duplicate_of")}
    runs = {p.stem: [r for r in load(p) if r["id"] in labels] for p in sorted(RUNS.glob("*.jsonl"))}
    if not runs:
        print("нет прогонов в runs/")
        return

    configs: dict[str, list[dict]] = dict(runs)
    is_cheap = lambda k: "haiku" in k or "lite" in k  # noqa: E731
    for cheap in [k for k in runs if is_cheap(k)]:
        rest = cheap.split("__", 1)[1]
        family = cheap.split("-")[0]
        for strong in [k for k in runs if not is_cheap(k) and k.startswith(family) and k.split("__", 1)[1] == rest]:
            configs[f"cascade: {cheap.split('__')[0]} → {strong.split('__')[0]}__{rest}"] = cascade(runs[cheap], runs[strong])

    summary = {name: score(rows, labels) for name, rows in configs.items()}
    for name, rows in configs.items():
        if name.startswith("cascade"):
            summary[name]["escalated_share"] = sum(1 for r in rows if r.get("escalated")) / len(rows)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    n_img = len(labels)
    n_ev = sum(1 for x in labels.values() if x["is_event"])
    games = Counter(x["game"] for x in labels.values())
    lines = [
        "# Результаты",
        "",
        f"Набор: {n_img} скриншотов без дублей, из них {n_ev} экранов событий и {n_img - n_ev} обычного геймплея. "
        + ", ".join(f"{g} {c}" for g, c in games.most_common()) + ".",
        "",
        "| Конфигурация | Событие: точность / полнота | Название | Механика (главная) | $ на 1000 скриншотов | Время p50 / p90, с |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in sorted(summary.items(), key=lambda kv: kv[1]["cost_per_1000"]):
        d = s["detection"]
        lines.append(
            f"| {name.replace('__', ' · ')} | {pct(d['precision'])} / {pct(d['recall'])} | {pct(s['name_acc'])} ({ci(s['name_ci'])}) | "
            f"{pct(s['mechanic_main_acc'])} ({ci(s['mechanic_ci'])}) | ${s['cost_per_1000']:.2f} | {s['latency_p50']:.1f} / {s['latency_p90']:.1f} |"
        )
    lines += ["", "В скобках 95 % доверительный интервал (bootstrap по скриншотам).", ""]

    # где ошибается лучшая по механике конфигурация
    best = max((k for k in configs if not k.startswith("cascade")), key=lambda k: summary[k]["mechanic_main_acc"])
    confusion = Counter()
    misses = defaultdict(list)
    for r in configs[best]:
        lab = labels[r["id"]]
        if not (r.get("reading") and lab["is_event"] and lab.get("mechanic")):
            continue
        pred = (r["reading"]["mechanics"] or ["—"])[0]
        if pred not in lab["mechanics_ok"]:
            confusion[(lab["mechanic"], pred)] += 1
            misses[(lab["mechanic"], pred)].append(lab["source_page"])
    if confusion:
        lines += [f"## Где путается {best.split('__')[0]}", "", "| Эталон | Ответ | Сколько | Пример |", "|---|---|---|---|"]
        for (t, p), c in confusion.most_common(12):
            lines.append(f"| {t} | {p} | {c} | {misses[(t, p)][0]} |")
        lines.append("")
    (RESULTS / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:len(summary) + 8]))


if __name__ == "__main__":
    main()
