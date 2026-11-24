"""Сбор скриншотов LiveOps-событий и обычного геймплея с вики игр на Fandom.

Картинки сохраняются в data/images (в git не попадают), описание каждой
картинки с источником в data/manifest.jsonl. Метка события берётся из вики:
страница события даёт название, её категории и вводный текст нужны для
разметки механики.

Запуск: uv run python data/collect.py
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
IMAGES = ROOT / "images"
MANIFEST = ROOT / "manifest.jsonl"
UA = {"User-Agent": "liveops-vision/0.1 (research demo; contact via github.com/matbcontrol)"}

# game, wiki, категории страниц событий, категории страниц обычного геймплея
SOURCES = [
    ("Candy Crush Saga", "candycrush", ["Events"], []),
    ("Royal Match", "royalmatch", ["Events", "Solo Events", "Team Events"], ["Gameplay", "Areas", "Indoor Areas", "Outdoor Areas"]),
    ("Township", "township", ["Events"], ["Gameplay", "Community Buildings", "Special Buildings"]),
    ("Homescapes", "homescapes", ["Events"], ["Gameplay", "Levels", "Levels 1-100", "Boosters"]),
    ("Gardenscapes", "gardenscapes", ["Events"], ["Gameplay", "Levels", "Areas"]),
]
# обычные уровни Candy Crush лежат в категориях вида «X levels»
CANDY_LEVEL_CATEGORIES = [
    "Apple Alley levels", "Banana Bay levels", "Biscuit Bay levels", "Berry Bazaar levels", "Blueberry Bluffs levels",
    "Apple Abode levels", "Apricot Alley levels", "Bakers Bluff levels", "Balloon Barn levels", "Banana Beach levels",
    "Biscuit Borough levels", "Blooming Bakery levels", "Board Game Basement levels", "Almond Airport levels",
]

MAX_EVENT_PAGES = 45
MAX_IMAGES_PER_PAGE = 4
MAX_REGULAR_PER_GAME = 30
SKIP_TITLE = re.compile(r"icon|logo|avatar|badge|banner_small|emoji|sprite|button|portrait|character", re.I)


def api(wiki: str, **params) -> dict:
    params = {"format": "json", **params}
    for attempt in range(3):
        try:
            r = requests.get(f"https://{wiki}.fandom.com/api.php", params=params, headers=UA, timeout=30)
            r.raise_for_status()
            time.sleep(0.2)
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def category_pages(wiki: str, category: str) -> list[str]:
    out, cont = [], {}
    while True:
        j = api(wiki, action="query", list="categorymembers", cmtitle=f"Category:{category}", cmlimit=500, cmnamespace=0, **cont)
        out += [p["title"] for p in j.get("query", {}).get("categorymembers", [])]
        if "continue" not in j:
            return out
        cont = {"cmcontinue": j["continue"]["cmcontinue"]}


def page_info(wiki: str, title: str) -> tuple[list[str], str]:
    """Категории страницы и начало вики-текста без разметки."""
    j = api(wiki, action="query", prop="categories|revisions", titles=title, cllimit=50, rvprop="content", rvslots="main")
    page = next(iter(j.get("query", {}).get("pages", {}).values()), {})
    cats = [c["title"].removeprefix("Category:") for c in page.get("categories", [])]
    text = ""
    revs = page.get("revisions") or []
    if revs:
        text = revs[0].get("slots", {}).get("main", {}).get("*", "")
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", " ", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<[^>]+>|'''?|==+", " ", text)
    return cats, re.sub(r"\s+", " ", text).strip()[:1500]


def page_images(wiki: str, title: str) -> list[dict]:
    j = api(wiki, action="query", generator="images", titles=title, gimlimit=50, prop="imageinfo", iiprop="size|url|mime")
    out = []
    for im in j.get("query", {}).get("pages", {}).values():
        ii = (im.get("imageinfo") or [None])[0]
        if not ii:
            continue
        w, h, mime = ii["width"], ii["height"], ii.get("mime", "")
        ratio = h / w if w else 0
        if w < 480 or h < 400 or not re.search(r"png|jpe?g|webp", mime) or SKIP_TITLE.search(im["title"]):
            continue
        if 0.85 < ratio < 1.15:  # квадратные картинки на вики почти всегда арт, а не скриншоты
            continue
        out.append({"file_title": im["title"], "url": ii["url"], "width": w, "height": h, "mime": mime})
    return sorted(out, key=lambda x: x["file_title"])


URL_INDEX = ROOT / "url_index.json"
_url_index: dict[str, list[str]] = json.loads(URL_INDEX.read_text(encoding="utf-8")) if URL_INDEX.exists() else {}


def download(url: str, game: str) -> tuple[str, str] | None:
    if url in _url_index and (ROOT.parent / _url_index[url][0]).exists():
        return tuple(_url_index[url])  # уже скачано в прошлый запуск
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
    except requests.RequestException:
        return None
    sha = hashlib.sha1(r.content).hexdigest()
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(r.headers.get("content-type", "").split(";")[0], ".png")
    folder = IMAGES / re.sub(r"\W+", "_", game.lower())
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha[:16]}{ext}"
    path.write_bytes(r.content)
    rel = str(path.relative_to(ROOT.parent)).replace("\\", "/")
    _url_index[url] = [rel, sha]
    return rel, sha


def collect() -> None:
    rows, seen = [], set()
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rows.append(row)
            seen.add(row["sha1"])

    done_pages = {(r["game"], r["page"]) for r in rows}

    def save():
        MANIFEST.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        URL_INDEX.write_text(json.dumps(_url_index), encoding="utf-8")

    def add_page(game, wiki, kind, page, limit):
        if (game, page) in done_pages:
            return sum(1 for r in rows if r["game"] == game and r["page"] == page)
        cats, intro = page_info(wiki, page)
        imgs = page_images(wiki, page)[:limit]
        with ThreadPoolExecutor(6) as ex:
            got = list(ex.map(lambda im: download(im["url"], game), imgs))
        n = 0
        for img, g in zip(imgs, got):
            if not g or g[1] in seen:
                continue
            path, sha = g
            seen.add(sha)
            rows.append({
                "id": sha[:16], "game": game, "wiki": wiki, "kind": kind, "page": page,
                "event_name": page if kind == "event" else None, "page_categories": cats, "wiki_intro": intro,
                **img, "path": path, "sha1": sha,
                "source_page": f"https://{wiki}.fandom.com/wiki/{page.replace(' ', '_')}",
            })
            n += 1
        done_pages.add((game, page))
        save()
        return n

    for game, wiki, event_cats, regular_cats in SOURCES:
        pages = []
        for c in event_cats:
            pages += [p for p in category_pages(wiki, c) if p not in pages]
        n_ev = sum(add_page(game, wiki, "event", t, MAX_IMAGES_PER_PAGE) for t in pages[:MAX_EVENT_PAGES])
        regular_pages = []
        for c in (CANDY_LEVEL_CATEGORIES if wiki == "candycrush" else regular_cats):
            regular_pages += category_pages(wiki, c)[:6]
        n_reg = 0
        for title in regular_pages:
            if n_reg >= MAX_REGULAR_PER_GAME:
                break
            n_reg += add_page(game, wiki, "regular", title, 2)
        print(f"{game}: event pages {len(pages)}, event images {n_ev}, regular {n_reg}", flush=True)

    print("total images:", len(rows))


if __name__ == "__main__":
    collect()
