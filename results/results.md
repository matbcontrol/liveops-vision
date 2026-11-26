# Results

370 screenshots after near-duplicate removal: 265 event screens (195 with a mechanic label) and 105 ordinary screens. Township 176, Candy Crush Saga 118, Gardenscapes 32, Homescapes 24, Royal Match 20.

| Configuration | Event: precision / recall | Main mechanic | Title | $ per 1000 screenshots | Latency p50 / p90 |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite · 1024 px · prompt v2 | 98.5 % / 96.6 % | 83.1 % (78–88 %) | 67.0 % | $0.87 | 5.0 / 23.7 s |
| gemini-3.5-flash-lite · 1024 px · prompt v1 | 84.7 % / 98.5 % | 78.5 % (73–84 %) | 66.5 % | $0.94 | 2.4 / 3.7 s |
| gemini-3.5-flash-lite · 1024 px · prompt v2 | 98.1 % / 96.2 % | 79.5 % (74–85 %) | 66.4 % | $0.96 | 3.1 / 8.2 s |
| gemini-3.5-flash-lite · 512 px · prompt v2 | 98.1 % / 97.4 % | 76.9 % (71–83 %) | 66.8 % | $0.96 | 2.9 / 4.8 s |
| cascade: gemini-3.5-flash-lite · 1024 px · prompt v2 → gemini-3.6-flash (escalated 4.3 %) | 98.8 % / 95.1 % | 79.5 % (74–85 %) | 66.4 % | $1.08 | 3.1 / 8.5 s |

Brackets: 95 % bootstrap interval over screenshots. Cost at paid-tier prices; the runs themselves used the free tier.

Partial runs (free-tier daily limits), not in the table: gemini-3.6-flash · 1024 px · prompt v1 (46 screenshots), gemini-3.6-flash · 1024 px · prompt v2 (16 screenshots)

## gemini-3.1-flash-lite · 1024 px · prompt v2: by game

| Game | Screenshots | Events found | False alarms on ordinary screens | Main mechanic |
|---|---|---|---|---|
| Township | 176 | 98/103 | 4/73 | 91.8 % (73) |
| Candy Crush Saga | 118 | 96/100 | 0/18 | 80.3 % (61) |
| Gardenscapes | 32 | 32/32 | 0/0 | 64.5 % (31) |
| Homescapes | 24 | 21/21 | 0/3 | 85.7 % (21) |
| Royal Match | 20 | 9/9 | 0/11 | 88.9 % (9) |

## Does the model know when it is wrong? (gemini-3.1-flash-lite · 1024 px · prompt v2)

| Self-reported confidence | Screenshots | Fully right |
|---|---|---|
| high | 360 | 88.6 % |
| medium | 10 | 90.0 % |

## Two cheap models as an error detector (gemini-3.1-flash-lite vs gemini-3.5-flash-lite)

| | Screenshots | First model fully right |
|---|---|---|
| models agree | 301 | 91.4 % |
| models disagree | 69 | 76.8 % |

Which rule finds the first model's mistakes (42 of 370 screenshots are not fully right):

| Escalation rule | Sent to the strong model | Mistakes caught |
|---|---|---|
| low confidence or mechanic "Other" | 21 (5.7 %) | 5 of 42 (11.9 %) |
| two cheap models disagree | 69 (18.6 %) | 16 of 42 (38.1 %) |
| either | 76 (20.5 %) | 17 of 42 (40.5 %) |

## Where the mechanic goes wrong (gemini-3.1-flash-lite · 1024 px · prompt v2)

| Label | Answer | Count | Example |
|---|---|---|---|
| Leaderboard | Collection | 5 | https://candycrush.fandom.com/wiki/All_Stars |
| Core Duplicates | Collection | 4 | https://candycrush.fandom.com/wiki/Cake_Crumbs |
| Digging | Collection | 3 | https://candycrush.fandom.com/wiki/Baker's_Box |
| Other | Collection | 2 | https://candycrush.fandom.com/wiki/Booster_Drop |
| Other | not an event | 2 | https://township.fandom.com/wiki/Aerial_Challenge_Event |
| Expedition | Other | 2 | https://gardenscapes.fandom.com/wiki/Dog_Training |
| Collection | Leaderboard | 1 | https://candycrush.fandom.com/wiki/2023_Jonas_Brothers_events |
| Leaderboard | Lava Quest | 1 | https://candycrush.fandom.com/wiki/All_Stars |
| Other | Login Calendar | 1 | https://candycrush.fandom.com/wiki/Booster_Drop |
| Win Streak | not an event | 1 | https://candycrush.fandom.com/wiki/Candy_Necklace |
