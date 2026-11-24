"""Дополнительные экраны без событий: категории файлов со скриншотами на вики.

Берутся файлы, в названии которых нет слов, связанных с событиями. Потом всё
равно проверяются глазами (review.json): на скриншоте города может оказаться
окно события.

Запуск: uv run python data/collect_negatives.py
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collect import MANIFEST, URL_INDEX, _url_index, api, download  # noqa: E402

SOURCES = [("Township", "township", "Screenshots", 90), ("Township", "township", "Screenshots jpg", 30)]
EVENTISH = re.compile(r"event|pass|ticket|season|contest|competition|tournament|race|cup|festival|christmas|halloween|easter|valentine|offer|sale|prize|reward|bonus", re.I)


def files_in(wiki: str, category: str, limit: int) -> list[dict]:
    out, cont = [], {}
    while len(out) < limit * 3:
        j = api(wiki, action="query", generator="categorymembers", gcmtitle=f"Category:{category}", gcmtype="file",
                gcmlimit=200, prop="imageinfo", iiprop="size|url|mime", **cont)
        for p in j.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or EVENTISH.search(p["title"]):
                continue
            w, h = ii["width"], ii["height"]
            if w < 640 or h < 360 or not (h / w > 1.3 or h / w < 0.77):
                continue
            out.append({"file_title": p["title"], "url": ii["url"], "width": w, "height": h, "mime": ii.get("mime", "")})
        if "continue" not in j:
            break
        cont = {"gcmcontinue": j["continue"]["gcmcontinue"]}
    return sorted(out, key=lambda x: x["file_title"])[:limit]


def main() -> None:
    rows = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen = {r["sha1"] for r in rows}
    added = 0
    for game, wiki, cat, limit in SOURCES:
        files = files_in(wiki, cat, limit)
        with ThreadPoolExecutor(6) as ex:
            got = list(ex.map(lambda f: download(f["url"], game), files))
        for f, g in zip(files, got):
            if not g or g[1] in seen:
                continue
            seen.add(g[1])
            rows.append({"id": g[1][:16], "game": game, "wiki": wiki, "kind": "regular", "page": f"Category:{cat}",
                         "event_name": None, "page_categories": [cat], "wiki_intro": "", **f, "path": g[0], "sha1": g[1],
                         "source_page": f"https://{wiki}.fandom.com/wiki/{f['file_title'].replace(' ', '_')}"})
            added += 1
        print(f"{game} / {cat}: {len(files)} files", flush=True)
    MANIFEST.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    URL_INDEX.write_text(json.dumps(_url_index), encoding="utf-8")
    print("added", added)


if __name__ == "__main__":
    main()
