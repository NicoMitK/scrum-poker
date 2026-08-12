# 🃏 Scrum Poker

[![CI](https://github.com/NicoMitK/scrum-poker/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NicoMitK/scrum-poker/actions/workflows/ci.yml)

Real-time planning poker for the team. Pure Python standard library, no dependencies.

## What it does

- Pick a name and a role: **Product Owner** 👑 or **Technical Operations** 🛠️
- Everyone sits around a table and picks a card: `0.25 · 0.5 · 1 · 2 · 3 · 5 · 8 · 13 · 21+ · ☕`
- Cards stay face down until the Product Owner hits **Reveal cards**
- Revealing before everybody voted asks for confirmation and names who is missing
- After reveal: average, lowest, highest, 🎉 on consensus
- Product Owner only: **Reveal cards**, **Reset votes** (same round), **New round**,
  **Restart voting** (back to round 1), and removing a participant via the **×** on their seat
- The table resets itself to round 1 as soon as the last person leaves
- Everything updates live for everybody — no refresh

`21+` counts as 21 in the average, ☕ means "skip" and is left out of the statistics.

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
python -m unittest discover -s tests -v   # 46 tests
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
| `GET` | `/api/state` | Current state for the caller (`X-Poker-Token` header) |
| `GET` | `/api/events?token=…` | Server-Sent Events stream |
| `POST` | `/api/join` | `{name, role}` → `{token, state}` |
| `POST` | `/api/vote` | `{card}` — the same card again takes it back |
| `POST` | `/api/reveal` | Product Owner only |
| `POST` | `/api/reset` | Product Owner only — next round |
| `POST` | `/api/restart` | Product Owner only — back to round 1 |
| `POST` | `/api/remove` | `{id}` — Product Owner removes a participant |
| `POST` | `/api/leave` | Leaves the table |

State lives in memory, so a restart clears the table. A seat survives a page refresh; a closed
tab disappears after ~40 seconds. One seat per browser profile — use a private window to test
a second participant. To change the deck edit `DECK` and `CARD_VALUES` in [server.py](server.py).
