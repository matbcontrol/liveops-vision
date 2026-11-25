# LiveOps Vision

Reads mobile game screenshots and tells which LiveOps event is on screen: is it an event at all, its title, its mechanic in [AppMagic's LiveOps taxonomy](https://appmagic.rocks/files/img-blog/Casual_LiveOps_Report_H1_2025.pdf) (Race, Album, Win Streak, Lava Quest, Digging and the rest), the timer and the rewards. Every answer is checked against labels, and every model call is logged with its cost and latency, so the choice of model is a measured trade-off rather than a guess.

Today this work is done by people: Sensor Tower says its LiveOps team logs hundreds of hours of play to capture events across the top 180 games. The question this repo answers is how much of that a vision model can read, how well, and at what price per thousand screenshots.

## Results

370 screenshots from five casual games (Township, Candy Crush Saga, Gardenscapes, Homescapes, Royal Match): 265 event screens, 195 of them with a mechanic label, and 105 ordinary screens. Full tables, per-game breakdown and error lists: [results/results.md](results/results.md).

| Gemini 3.5 Flash-Lite, 1024 px | Event: precision / recall | Main mechanic | $ per 1000 screenshots | Latency p50 |
|---|---|---|---|---|
| prompt v1 | 84.7 % / 98.5 % | 78.5 % (73–84 %) | $0.94 | 2.4 s |
| prompt v2 (permanent-features rule) | **98.1 % / 96.2 %** | **79.5 % (74–85 %)** | $0.96 | 3.1 s |

Brackets are 95 % bootstrap intervals. Cost is at paid-tier prices; the runs used the free tier.

What the numbers say:

- **Finding events is cheap and reliable; naming the mechanic is the hard part.** About one screenshot in five gets the wrong main mechanic. The usual confusions are close neighbours: a leaderboard read as Race or Collection, special levels (Core Duplicates) read as Collection. Many events combine mechanics, so the second-best answer is often right: the labelled mechanic is among the model's answers in 86 % of cases.
- **The real trap is permanent meta, not events.** Version 1 flagged 46 of 74 ordinary Township screens as events: the museum collection, the airport, factories. They look exactly like event progress screens. One rule in the prompt (no timer, no event banner, no event points means a permanent feature) cut false alarms from 48 to 6 and cost 2.3 points of recall. The rule was written after looking at v1's errors, so this gain is an upper estimate until it is checked on fresh screenshots.
- **Self-reported confidence is not a signal.** The model says "high" on 359 of 370 screenshots and is fully right on 87 % of them. A cascade that escalates on low confidence would send almost nothing to the stronger model. Disagreement between two cheap models is the better trigger (see results).
- **Scale.** At these prices, reading 50 screenshots a day from each of 180 games costs about $9 a day before the duplicate check removes repeated screens.

Not measured yet, because free-tier daily limits allow 20 requests to the stronger Flash models: the cascade into Gemini 3.6 Flash, the 512 px trade-off, and the Claude path.

## How it works

```
screenshot ──> OpenCV ──────────────> cheap model ──(sure?)──> answer ──> Postgres: events calendar
               │ same screen seen       flash-lite / haiku │ no
               │ before? reuse answer                      └──> stronger model (flash / sonnet)
               └ downscale to 1024 px long edge
```

The same schema, prompt and cost logging run on two providers: Gemini (`liveops_vision/gemini.py`) and Claude (`liveops_vision/extract.py`). The measured results below are from Gemini models on the free tier, with cost computed at paid-tier prices. The Claude path is covered by tests against a mocked client and has not been measured on this dataset yet.

- **OpenCV before the model.** A near-duplicate check (shape hash plus a 16×16 colour thumbnail) skips screens that were already read; a shape hash alone merges different events drawn in the same pop-up template, which the tests cover. Images are downscaled because image tokens grow with pixel area, not with information.
- **Structured output.** The answer is constrained to a JSON schema (`liveops_vision/schema.py`), so it always parses: screen type, event flag, title as written, mechanics, motivations, timer, rewards, confidence and one sentence of evidence.
- **Cascade.** The cheap model reads everything. When it is not confident, or it calls the mechanic "Other", the screenshot goes to the strong model. The rule is one function (`metrics.needs_escalation`) and is evaluated on the same data as the single models.
- **Service.** `liveops_vision/service.py` is a FastAPI app: upload a screenshot with its capture date, get the reading; `GET /games/{game}/events` returns the events calendar with first and last day seen. A repeat screenshot of the same screen extends the event without a model call. Tested on SQLite and on a real Postgres (`pgserver`), which caught a foreign-key ordering bug SQLite let through.

## Data and labels

Screenshots come from the fan wikis of Candy Crush Saga, Royal Match, Township, Homescapes and Gardenscapes on Fandom: event pages give event screenshots, level and area pages give ordinary gameplay. The images are not in this repository; `data/collect.py` downloads them and `data/manifest.jsonl` keeps the source of every file.

- **Event or not** comes from the page the image is on.
- **Title** is the event page title. Pages that cover several events at once are not used for the title metric.
- **Mechanic** was assigned by hand from the event's text description on the wiki (`data/event_mechanics.json`). The model sees only the picture, so the label comes from an independent source. Events whose description does not make the mechanic clear have no mechanic label and count only for detection and title.

Limits: wiki screenshots are curated, mostly pop-ups and progress screens; real capture from devices has more noise, notifications and partial screens. Titles are compared after normalisation with a fuzzy threshold. Confidence intervals are bootstrap over screenshots.

## When not to use RAG or a graph framework

There is no retrieval here on purpose. Each screenshot carries everything needed to read it, and the taxonomy fits in the system prompt. Retrieval starts to pay off for the update-diff task: find the previous version of the same screen across thousands of captures, then compare. The same goes for LangGraph: a two-step cascade with one branch is twenty lines of testable Python. A graph earns its place when the flow becomes stateful and loops, for example diffing a game update: retrieve the old screen, compare regions (`preprocess.changed_regions`), ask for crops, repeat until every change is explained, send unclear cases to an analyst.

## Run

```
uv sync
uv run python data/collect.py          # download screenshots (~350 files)
uv run python data/build_labels.py     # labels + near-duplicate check
# keys in .env (git-ignored): GEMINI_API_KEY=... and/or ANTHROPIC_API_KEY=...
uv run python -m liveops_vision.run --models gemini-3.5-flash-lite gemini-3.6-flash --max-side 1024
uv run python -m liveops_vision.run --models claude-haiku-5-5 claude-sonnet-5-5 --max-side 1024
uv run python -m liveops_vision.report # results/results.md
uv run uvicorn liveops_vision.service:app
uv run pytest
```

A finished run is resumable: answers are appended to `runs/*.jsonl`, and a restart skips screenshots that already have one, so an interrupted run never pays twice.
