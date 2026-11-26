# LiveOps Vision

Reads mobile game screenshots and tells which LiveOps event is on screen: is it an event at all, its title, its mechanic in [AppMagic's LiveOps taxonomy](https://appmagic.rocks/files/img-blog/Casual_LiveOps_Report_H1_2025.pdf) (Race, Album, Win Streak, Lava Quest, Digging and the rest), the timer and the rewards. Every answer is checked against labels, and every model call is logged with its cost and latency, so the choice of model is a measured trade-off rather than a guess.

Today this work is done by people: Sensor Tower says its LiveOps team logs hundreds of hours of play to capture events across the top 180 games. The question this repo answers is how much of that a vision model can read, how well, and at what price per thousand screenshots.

## Results

370 screenshots from five casual games (Township, Candy Crush Saga, Gardenscapes, Homescapes, Royal Match): 265 event screens, 195 of them with a mechanic label, and 105 ordinary screens. Full tables, per-game breakdown and error lists: [results/results.md](results/results.md).

| Configuration | Event: precision / recall | Main mechanic | $ per 1000 screenshots | Latency p50 / p90 |
|---|---|---|---|---|
| Gemini 3.5 Flash-Lite, 1024 px, prompt v1 | 84.7 % / 98.5 % | 78.5 % (73–84 %) | $0.94 | 2.4 / 3.7 s |
| Gemini 3.5 Flash-Lite, 1024 px, prompt v2 (permanent-features rule) | 98.1 % / 96.2 % | 79.5 % (74–85 %) | $0.96 | 3.1 / 8.2 s |
| Gemini 3.5 Flash-Lite, 512 px, prompt v2 | 98.1 % / 97.4 % | 76.9 % (71–83 %) | $0.96 | 2.9 / 4.8 s |
| Gemini 3.1 Flash-Lite, 1024 px, prompt v2 | **98.5 % / 96.6 %** | **83.1 % (78–88 %)** | $0.87 | 5.0 / 23.7 s |
| 3.5 Flash-Lite v2, unsure screens sent to Gemini 3.6 Flash (4.3 %) | 98.8 % / 95.1 % | 79.5 % (74–85 %) | $1.08 | 3.1 / 8.5 s |

Brackets are 95 % bootstrap intervals. Cost is at paid-tier prices; the runs used the free tier, which was overloaded during the 3.1 Flash-Lite run, so its latency says more about the free tier than about the model.

What the numbers say:

- **Finding events is cheap and reliable; naming the mechanic is the hard part.** One screenshot in five or six gets the wrong main mechanic. The usual confusions are close neighbours: a leaderboard read as Race or Collection, special levels (Core Duplicates) read as Collection. Many events combine mechanics, so the second-best answer is often right: for 3.5 Flash-Lite the labelled mechanic is among its answers in 86 % of cases.
- **The real trap is permanent meta, not events.** Version 1 flagged 46 of 74 ordinary Township screens as events: the museum collection, the airport, factories. They look exactly like event progress screens. One rule in the prompt (no timer, no event banner, no event points means a permanent feature) cut false alarms from 48 to 6 and cost 2.3 points of recall. The rule was written after looking at v1's errors, so this gain is an upper estimate until it is checked on fresh screenshots.
- **Self-reported confidence is not a signal.** Both cheap models say "high" on 359–360 of 370 screenshots. The cascade above sent the 16 screens where 3.5 Flash-Lite was unsure (or said "Other") to Gemini 3.6 Flash: the cheap model had 13 of them right, the strong model 12. Accuracy did not move and the bill grew by 12 %.
- **Disagreement between two cheap models finds mistakes better.** With 3.1 Flash-Lite as the main model and 3.5 Flash-Lite as a second opinion, the two disagree on 69 screenshots (19 %), and those hold 16 of its 42 mistakes. The confidence rule flags 21 screenshots and holds 5. How much a strong model fixes on those 69 is not measured yet: the free tier allows 20 requests a day to the Flash models.
- **On Gemini, a smaller picture is not cheaper.** A request costs 2 020 input tokens at both 512 and 1024 px, because Gemini bills a fixed number of tokens per image. Going down to 512 px saved nothing and cost 2.6 points of mechanic accuracy (inside the interval). Claude bills by pixel area, so there the trade-off is real.
- **Scale.** At these prices, reading 50 screenshots a day from each of 180 games costs about $8–9 a day before the duplicate check removes repeated screens.

Not measured yet: a strong model on the screenshots where the two cheap models disagree, and the Claude path.

## How it works

```
screenshot ──> OpenCV ──────────────> cheap model ──(sure?)──> answer ──> Postgres: events calendar
               │ same screen seen       flash-lite / haiku │ no
               │ before? reuse answer                      └──> stronger model (flash / sonnet)
               └ downscale to 1024 px long edge
```

The same schema, prompt and cost logging run on two providers: Gemini (`liveops_vision/gemini.py`) and Claude (`liveops_vision/extract.py`). The measured results below are from Gemini models on the free tier, with cost computed at paid-tier prices. The Claude path is covered by tests against a mocked client and has not been measured on this dataset yet.

- **OpenCV before the model.** A near-duplicate check (shape hash plus a 16×16 colour thumbnail) skips screens that were already read; a shape hash alone merges different events drawn in the same pop-up template, which the tests cover. Images are downscaled to a long edge of 1024 px: on Claude image tokens grow with pixel area, on Gemini the size only changes upload time (see Results).
- **Structured output.** The answer is constrained to a JSON schema (`liveops_vision/schema.py`), so it always parses: screen type, event flag, title as written, mechanics, motivations, timer, rewards, confidence and one sentence of evidence.
- **Cascade.** The cheap model reads everything, and a rule decides which screenshots go to the strong model. Two rules are measured on the same data as the single models: low confidence or mechanic "Other" (`metrics.needs_escalation`) and disagreement between two cheap models (`metrics.disagree`, `run.py --only disagree:...`).
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

Runs are resumable: answers are appended to `runs/*.jsonl`, a restart skips screenshots that already have an answer and retries calls that failed (quota, 503), so an interrupted run never pays twice.
