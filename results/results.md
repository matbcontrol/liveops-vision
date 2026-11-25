# Results

370 screenshots after near-duplicate removal: 265 event screens (195 with a mechanic label) and 105 ordinary screens. Township 176, Candy Crush Saga 118, Gardenscapes 32, Homescapes 24, Royal Match 20.

| Configuration | Event: precision / recall | Main mechanic | Title | $ per 1000 screenshots | Latency p50 / p90 |
|---|---|---|---|---|---|
| gemini-3.5-flash-lite · 1024 px · prompt v1 | 84.7 % / 98.5 % | 78.5 % (73–84 %) | 66.5 % | $0.94 | 2.4 / 3.7 s |
| gemini-3.5-flash-lite · 1024 px · prompt v2 | 98.1 % / 96.2 % | 79.5 % (74–85 %) | 66.4 % | $0.96 | 3.1 / 8.2 s |
| cascade: gemini-3.5-flash-lite · 1024 px · prompt v1 → gemini-3.6-flash (escalated 0.3 %) | 84.7 % / 98.5 % | 78.5 % (73–84 %) | 66.5 % | $0.94 | 2.4 / 3.7 s |

Brackets: 95 % bootstrap interval over screenshots. Cost at paid-tier prices; the runs themselves used the free tier.

Partial runs (free-tier daily limits), not in the table: gemini-3.1-flash-lite · 1024 px · prompt v2 (4 screenshots), gemini-3.5-flash-lite · 512 px · prompt v2 (6 screenshots), gemini-3.6-flash · 1024 px · prompt v1 (46 screenshots)

## gemini-3.5-flash-lite · 1024 px · prompt v2: by game

| Game | Screenshots | Events found | False alarms on ordinary screens | Main mechanic |
|---|---|---|---|---|
| Township | 176 | 97/103 | 3/73 | 86.3 % (73) |
| Candy Crush Saga | 118 | 96/100 | 0/18 | 77.0 % (61) |
| Gardenscapes | 32 | 32/32 | 0/0 | 71.0 % (31) |
| Homescapes | 24 | 21/21 | 1/3 | 76.2 % (21) |
| Royal Match | 20 | 9/9 | 1/11 | 77.8 % (9) |

## Does the model know when it is wrong? (gemini-3.5-flash-lite · 1024 px · prompt v2)

| Self-reported confidence | Screenshots | Fully right |
|---|---|---|
| high | 359 | 86.9 % |
| medium | 11 | 72.7 % |

## Where the mechanic goes wrong (gemini-3.5-flash-lite · 1024 px · prompt v2)

| Label | Answer | Count | Example |
|---|---|---|---|
| Core Duplicates | Collection | 4 | https://candycrush.fandom.com/wiki/A_Magic_Trick |
| Leaderboard | Collection | 4 | https://candycrush.fandom.com/wiki/All_Stars |
| Leaderboard | Race | 3 | https://candycrush.fandom.com/wiki/Beat_the_Buffet |
| Other | Collection | 2 | https://candycrush.fandom.com/wiki/Booster_Drop |
| Other | Login Calendar | 2 | https://candycrush.fandom.com/wiki/Booster_Drop |
| Pass | Expedition | 2 | https://township.fandom.com/wiki/Arctic_Adventure_Event |
| Expedition | not an event | 2 | https://township.fandom.com/wiki/Christmas_Rescue_2019_Event |
| Customization/Decoration | Collection | 2 | https://gardenscapes.fandom.com/wiki/Colors_of_Life |
| Leaderboard | Core Duplicates | 2 | https://gardenscapes.fandom.com/wiki/Culinary_Battle |
| Collection | Leaderboard | 1 | https://candycrush.fandom.com/wiki/2023_Jonas_Brothers_events |
