# Privi Demo site

Step-by-step video walkthroughs of every Privi service, recorded from the live servers.
Hosted on Railway (service root directory: `demo-site`, built from `Dockerfile`).

- `index.html` — the page. Live status strip calls each service's `/health` from the browser.
- `videos/` — one `.webm` + poster per walkthrough.
- `recorder/` — `flows.json` holds the real responses captured on 2026-10-25; `player.html` replays them;
  `python recorder/record.py [flow ...]` re-records the videos with Playwright. To refresh a video, capture new
  responses from the live service, update `flows.json`, and re-run the recorder.
- `serve.py` — stdlib static server, `$PORT`, `/health`.

Copyright (c) 2026 Privi World Co. All rights reserved.
