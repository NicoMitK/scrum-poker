# 🃏 Scrum Poker

[![CI](https://github.com/NicoMitK/scrum-poker/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NicoMitK/scrum-poker/actions/workflows/ci.yml)

Real-time planning poker for the team. Pure Python standard library, no dependencies.

## What it does

- Enter a **team ID** (e.g. `TEAM42`) and your name, then pick a role:
  **Product Owner** 👑 or **Technical Operations** 🛠️
- Everybody with the same team ID shares one table; different IDs never see each other
- Share the table with the 🔗 button in the top bar — it copies a link like
  `https://your-app.onrender.com/table/TEAM42`. Opening it pre-fills the team ID.
- Technical Operations estimate with a hand of cards:
  `0.25 · 0.5 · 1 · 2 · 3 · 5 · 8 · 13 · 21+ · ☕`
- The Product Owner does not estimate. Where the others have their cards, they get the
  controls: **Reveal cards**, **Reset votes** / **New round**, **Restart voting** (back to
  round 1). They can also remove somebody via the **×** on their seat.
- Cards stay face down until the Product Owner reveals them
- Revealing before everybody voted asks for confirmation and names who is missing
- After reveal: average, lowest, highest, 🎉 on consensus
- A table resets to round 1 as soon as the last person leaves, and is forgotten entirely
- Everything updates live for everybody — no refresh

`21+` counts as 21 in the average, ☕ means "skip" and is left out of the statistics.
Team IDs are case-insensitive (`team42` = `TEAM42`), max 16 characters, `A-Z 0-9 - _`.

## Run it

```powershell
python server.py
```

Open <http://localhost:8000>. Options: `--port 8080`, `--host 127.0.0.1`.

## Host it

| Where | How |
| --- | --- |
| **Render** | New → Blueprint → pick this repo. [render.yaml](render.yaml) does the rest. |
| **Codespaces** | Code → Create codespace. Set port 8000 to **Public** in the PORTS tab. |
| **Your machine** | `.\share.ps1 -Cloudflare`, or forward port 8000 in VS Code and set it to **Public**. |

Visitors never need a login — only the port/tunnel has to be **Public**.

> GitHub Pages does not work: it only serves static files and this app needs a running server
> to share votes between browsers.

## Development

```powershell
python -m unittest discover -s tests -v   # 70 tests
ruff check .                              # linter
```

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs the tests on Python 3.11–3.13, the
linter, and a smoke test against a real server on every push and pull request. To let CI
trigger the deploy, add the Render deploy hook as the `RENDER_DEPLOY_HOOK_URL` repository
secret (otherwise Render just auto-deploys on push).

## How it works

| File | Purpose |
| --- | --- |
| [server.py](server.py) | HTTP server, in-memory room, REST endpoints + SSE stream |
| [static/](static) | `index.html`, `style.css`, `app.js` — the whole frontend |
| [tests/](tests) | Unit tests for the room logic, end-to-end tests over HTTP |

### API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/table/<TEAMID>` | Shareable link — serves the app with the team ID pre-filled |
| `GET` | `/api/state` | State for the caller (`X-Poker-Token`), or `?room=<TEAMID>` |
| `GET` | `/api/events?token=…` | Server-Sent Events stream |
| `POST` | `/api/join` | `{room, name, role}` → `{token, state}` |
| `POST` | `/api/vote` | `{card}` — the same card again takes it back (Technical Operations only) |
| `POST` | `/api/reveal` | Product Owner only |
| `POST` | `/api/reset` | Product Owner only — next round |
| `POST` | `/api/restart` | Product Owner only — back to round 1 |
| `POST` | `/api/remove` | `{id}` — Product Owner removes a participant |
| `POST` | `/api/leave` | Leaves the table |

The token returned by `/api/join` starts with the team ID, so every later request knows which
table it belongs to — a token from one table cannot touch another.

State lives in memory, so a restart clears every table. A seat survives a page refresh; a
closed tab disappears after ~40 seconds, and a table with nobody left is dropped. One seat per
browser profile per table — use a private window to test a second participant. To change the
deck edit `DECK` and `CARD_VALUES` in [server.py](server.py).
