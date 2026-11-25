"""Сводка по всем прогонам: results/summary.json и results/results.md.

    uv run python -m liveops_vision.report
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .metrics import calibration, cascade, disagree, main_mechanic, score

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def ci(c: tuple[float, float]) -> str:
    return f"{100 * c[0]:.0f}–{100 * c[1]:.0f} %"


def pretty(tag: str) -> str:
    model, side, effort, *rest = tag.split("__")
    prompt = rest[0] if rest else "v1"
    return f"{model} · {side.replace('side', '')} px · prompt {prompt}"


def correct(x: dict | None, lab: dict) -> bool:
    if not x:
        return False
    if lab["is_event"] != x["is_liveops_event"]:
        return False
    return not (lab["is_event"] and lab.get("mechanic")) or main_mechanic(x) in lab["mechanics_ok"]


def main() -> None:
    labels = {x["id"]: x for x in load(ROOT / "data" / "labels.jsonl") if not x.get("duplicate_of")}
    runs = {p.stem: [r for r in load(p) if r["id"] in labels] for p in sorted(RUNS.glob("*.jsonl"))}
    full = {k: v for k, v in runs.items() if len(v) >= 0.95 * len(labels)}
    partial = {k: v for k, v in runs.items() if k not in full}

    configs: dict[str, list[dict]] = {pretty(k): v for k, v in full.items()}
    # каскад: дешёвая модель + сильная там, где правило велит; только если у сильной есть ответы на эти скриншоты
    for cheap_tag, cheap_rows in full.items():
        if "lite" not in cheap_tag:
            continue
        for strong_tag, strong_rows in runs.items():
            if "lite" in strong_tag or strong_tag.split("__")[3:] != cheap_tag.split("__")[3:]:
                continue
            from .metrics import needs_escalation

            want = {r["id"] for r in cheap_rows if needs_escalation(r.get("reading"))}
            have = {r["id"] for r in strong_rows if r.get("reading")}
            if not want or len(want & have) < 0.9 * len(want):
                continue  # у сильной модели нет ответов на скриншоты, которые надо ей отдать
            mixed = cascade(cheap_rows, strong_rows)
            if any(r.get("escalated") for r in mixed):
                configs[f"cascade: {pretty(cheap_tag)} → {strong_tag.split('__')[0]}"] = mixed

    summary = {name: score(rows, labels) for name, rows in configs.items()}
    for name, rows in configs.items():
        if name.startswith("cascade"):
            summary[name]["escalated_share"] = sum(1 for r in rows if r.get("escalated")) / len(rows)
    RESULTS.mkdir(exist_ok=True)

    n_img = len(labels)
    n_ev = sum(1 for x in labels.values() if x["is_event"])
    games = Counter(x["game"] for x in labels.values())
    out = [
        "# Results",
        "",
        f"{n_img} screenshots after near-duplicate removal: {n_ev} event screens ({sum(1 for x in labels.values() if x['is_event'] and x.get('mechanic'))} with a mechanic label) "
        f"and {n_img - n_ev} ordinary screens. " + ", ".join(f"{g} {c}" for g, c in games.most_common()) + ".",
        "",
        "| Configuration | Event: precision / recall | Main mechanic | Title | $ per 1000 screenshots | Latency p50 / p90 |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in sorted(summary.items(), key=lambda kv: (kv[0].startswith("cascade"), kv[1]["cost_per_1000"])):
        d = s["detection"]
        extra = f" (escalated {pct(s['escalated_share'])})" if "escalated_share" in s else ""
        out.append(f"| {name}{extra} | {pct(d['precision'])} / {pct(d['recall'])} | {pct(s['mechanic_main_acc'])} ({ci(s['mechanic_ci'])}) | "
                   f"{pct(s['name_acc'])} | ${s['cost_per_1000']:.2f} | {s['latency_p50']:.1f} / {s['latency_p90']:.1f} s |")
    out += ["", "Brackets: 95 % bootstrap interval over screenshots. Cost at paid-tier prices; the runs themselves used the free tier.", ""]

    if partial:
        out += ["Partial runs (free-tier daily limits), not in the table: " + ", ".join(f"{pretty(k)} ({len(v)} screenshots)" for k, v in partial.items()), ""]

    best = max((k for k in configs if not k.startswith("cascade")), key=lambda k: (summary[k]["detection"]["f1"] + summary[k]["mechanic_main_acc"]))
    rows = configs[best]
    out += [f"## {best}: by game", "", "| Game | Screenshots | Events found | False alarms on ordinary screens | Main mechanic |", "|---|---|---|---|---|"]
    for g, _ in games.most_common():
        sub = {k: v for k, v in labels.items() if v["game"] == g}
        s = score([r for r in rows if r["id"] in sub], sub)
        d = s["detection"]
        out.append(f"| {g} | {s['n']} | {d['tp']}/{d['tp'] + d['fn']} | {d['fp']}/{d['fp'] + d['tn']} | {pct(s['mechanic_main_acc'])} ({s['mechanic_n']}) |")

    cal = calibration(rows, labels)
    out += ["", f"## Does the model know when it is wrong? ({best})", "", "| Self-reported confidence | Screenshots | Fully right |", "|---|---|---|"]
    for level in ("high", "medium", "low"):
        if level in cal:
            out.append(f"| {level} | {cal[level]['n']} | {pct(cal[level]['accuracy'])} |")

    lites = [k for k in full if "lite" in k and k.endswith("__v2") and "side1024" in k]
    if len(lites) >= 2:
        a, b = ({r["id"]: r for r in full[t]} for t in lites[:2])
        agree_ok, dis_ok, n_agree, n_dis = 0, 0, 0, 0
        for i, lab in labels.items():
            x, y = a.get(i, {}).get("reading"), b.get(i, {}).get("reading")
            if disagree(x, y):
                n_dis += 1
                dis_ok += correct(x, lab)
            else:
                n_agree += 1
                agree_ok += correct(x, lab)
        out += ["", f"## Two cheap models as an error detector ({' vs '.join(t.split('__')[0] for t in lites[:2])})", "",
                "| | Screenshots | First model fully right |", "|---|---|---|",
                f"| models agree | {n_agree} | {pct(agree_ok / n_agree) if n_agree else '—'} |",
                f"| models disagree | {n_dis} | {pct(dis_ok / n_dis) if n_dis else '—'} |"]
        summary["_disagreement"] = {"agree": n_agree, "agree_right": agree_ok, "disagree": n_dis, "disagree_right": dis_ok}

    confusion, example = Counter(), defaultdict(str)
    for r in rows:
        lab = labels[r["id"]]
        x = r.get("reading")
        if x and lab["is_event"] and lab.get("mechanic") and main_mechanic(x) not in lab["mechanics_ok"]:
            key = (lab["mechanic"], main_mechanic(x) or "not an event")
            confusion[key] += 1
            example[key] = example[key] or lab["source_page"]
    if confusion:
        out += ["", f"## Where the mechanic goes wrong ({best})", "", "| Label | Answer | Count | Example |", "|---|---|---|---|"]
        out += [f"| {t} | {p} | {c} | {example[(t, p)]} |" for (t, p), c in confusion.most_common(10)]

    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / "results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
