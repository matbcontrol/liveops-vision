"""manifest.jsonl + разметка механик → labels.jsonl.

- is_event: скриншот со страницы события на вики или со страницы обычного геймплея;
- event_name: заголовок страницы события; если страница описывает сразу
  несколько событий (заголовок во множественном числе), название не меряется;
- mechanic: главная механика по классификации AppMagic, поставлена вручную по
  текстовому описанию события на вики (файл event_mechanics.json); модель видит
  только картинку, так что метка взята из независимого источника;
- duplicate_of: почти одинаковые картинки (OpenCV) не идут в оценку дважды.

Запуск: uv run python data/build_labels.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from liveops_vision import preprocess as pp  # noqa: E402

MANIFEST = ROOT / "manifest.jsonl"
MECH = ROOT / "event_mechanics.json"
OUT = ROOT / "labels.jsonl"


def clean_title(t: str) -> str:
    return re.sub(r"[^\w\s'&!-]", "", t).strip()


def main() -> None:
    rows = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    mech = json.loads(MECH.read_text(encoding="utf-8")) if MECH.exists() else {}
    review = json.loads((ROOT / "review.json").read_text(encoding="utf-8"))["exclude"] if (ROOT / "review.json").exists() else {}
    rows = [r for r in rows if r["id"] not in review]
    sigs = {}
    for r in rows:
        try:
            sigs[r["id"]] = pp.signature(pp.load(ROOT.parent / r["path"]))
        except ValueError:
            r["broken"] = True
    owner = pp.dedupe(sigs)
    out = []
    missing = set()
    for r in rows:
        if r.get("broken"):
            continue
        is_event = r["kind"] == "event"
        key = f'{r["game"]}|{r["page"]}'
        m = mech.get(key, {}) if is_event else {}
        if is_event and not m:
            missing.add(key)
        if m.get("exclude"):
            continue
        out.append({
            "id": r["id"], "path": r["path"], "game": r["game"], "is_event": is_event,
            "event_name": clean_title(r["page"]) if is_event else None,
            "name_reliable": is_event and not re.search(r"\bevents\b|\d{4}", r["page"], re.I) and not m.get("name_unreliable"),
            "mechanic": m.get("mechanic"), "mechanics_ok": m.get("ok", [m["mechanic"]] if m.get("mechanic") else []),
            "duplicate_of": None if owner.get(r["id"], r["id"]) == r["id"] else owner[r["id"]],
            "source_page": r["source_page"], "file_title": r["file_title"], "width": r["width"], "height": r["height"],
        })
    OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    ev = [x for x in out if x["is_event"] and not x["duplicate_of"]]
    print(f"картинок {len(out)}, без дублей {sum(1 for x in out if not x['duplicate_of'])}, "
          f"событий {len(ev)}, с механикой {sum(1 for x in ev if x['mechanic'])}, обычных {sum(1 for x in out if not x['is_event'] and not x['duplicate_of'])}")
    if missing:
        print(f"нет механики для {len(missing)} страниц событий")


if __name__ == "__main__":
    main()
