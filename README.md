# 🃏 Scrum Poker

A tiny real-time planning-poker web app for the team. **No dependencies** — plain Python 3
standard library on the server, vanilla HTML/CSS/JS in the browser.

## Features

- **Role selection on first visit**: *Product Owner* 👑 or *Technical Operations* 🛠️
- **Poker table in the middle**, every participant sits around it with their card in front of them
- **Your own hand of cards** at the bottom: `0.25, 0.5, 1, 2, 3, 5, 8, 13, 21+, ☕`
  (`21+` = "too big, split it", ☕ = skip / no estimate)
- Votes stay **face down** until they are revealed
- Only the **Product Owner** sees the *Reveal cards* button
- If somebody has not voted yet, the Product Owner gets a confirmation:
  *"Not everyone has given their prediction yet… Reveal anyway?"* (with the missing names)
- After reveal: average, lowest, highest and a 🎉 consensus badge
- *New round* / *Reset votes* (Product Owner only)
- The Product Owner can **remove a participant**: hover the seat and click the **×**
  (handy for a colleague who left their tab open somewhere)
- Live updates for everybody via Server-Sent Events — no refresh needed

## Run it locally

```powershell
git clone https://github.com/NicoMitK/scrum-poker.git
cd scrum-poker
python server.py
```

Then open <http://localhost:8000>.

Options:

```powershell
python server.py --port 8080          # different port
python server.py --host 127.0.0.1     # local only (default is 0.0.0.0)
```

In VS Code you can also press <kbd>F5</kbd> (*Scrum Poker server*) or run the task
**Terminal → Run Task → Start Scrum Poker**.

## Hosting it on the web

### ⚠️ Why GitHub Pages does not work for this app

GitHub Pages is a **static** file host: it can deliver HTML, CSS and JS, but it cannot run
any server-side code. Scrum Poker needs a running process, because the table is *shared* —
one browser has to learn that somebody else picked a card. That happens in
[server.py](server.py) (in-memory room + Server-Sent Events). On Pages there is nobody to
run it, so every visitor would sit at their own private table.

Use one of the free options below instead — both run the real server.

### Option A: Render (free plan, deploys straight from this repo)

[render.yaml](render.yaml) already contains the full configuration.

1. Sign in at <https://render.com> with your GitHub account (free, no credit card).
2. **New → Blueprint**, pick the `scrum-poker` repository, confirm.
3. Render reads `render.yaml`, builds and starts
   `python server.py --host 0.0.0.0 --port $PORT`.
4. You get a permanent public URL like `https://scrum-poker-xxxx.onrender.com` that
   **anybody can open without a login**.

Every push to `main` redeploys automatically. On the free plan the service sleeps after
~15 minutes without traffic; the next visitor wakes it up (first request takes ~30-60 s)
and the table starts empty again, which is fine for planning sessions.

### Option B: GitHub Codespaces (stays inside GitHub, 60 free hours/month)

[.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) is already set up.

1. On the repo page: **Code → Codespaces → Create codespace on main**.
2. The server starts automatically and port `8000` is forwarded.
3. In the **PORTS** tab: right-click port 8000 → **Port Visibility → Public**.
4. Share the `https://<codespace>-8000.app.github.dev` URL — no login needed for visitors.

The URL lives as long as the codespace runs.

### Option C: your own machine, no deployment

See [share.ps1](share.ps1) — VS Code port forwarding or a Cloudflare quick tunnel.
Details in the next section.

## Share it from your own machine — without a login for them

**The important setting is the port visibility: `Public`.** Then anybody who has the link
can join, no GitHub/Microsoft account needed. Only *you* sign in once to create the tunnel.

1. Start the server (see above).
2. Open the **Ports** view: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> →
   *"Ports: Focus on Ports View"* (it also lives next to the Terminal tab).
3. Click **Forward a Port** and enter `8000`. VS Code creates a
   `https://<something>-8000.<region>.devtunnels.ms` URL.
4. Right-click the forwarded port → **Port Visibility → Public**.
   (*Private* — the default — would force every teammate to sign in with GitHub.)
5. Copy the **Forwarded Address** and send it to the team.

The tunnel lives as long as VS Code and the server are running.

### Alternative: Cloudflare quick tunnel (nobody logs in — not even you)

```powershell
.\share.ps1 -Cloudflare
```

The script starts the server, downloads `cloudflared.exe` once (it asks first) and prints a
public `https://<random>.trycloudflare.com` URL that opens without any account.
Keep the window open — closing it ends the tunnel.

Both variants publish a URL to the internet: anyone who has the link can join the table,
so treat the link as the "password" and check that this is fine with your IT policy.

### What does *not* work on this machine

`http://<your-ip>:8000` over the plain office LAN: Windows Firewall has an **inbound Block
rule for Python** (Domain + Public profile) and changing it requires admin rights. If IT
allows inbound TCP 8000 for `python.exe`, LAN sharing works without any tunnel:

```powershell
# needs an administrator shell
New-NetFirewallRule -DisplayName "Scrum Poker 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain
```

- **Any host with Python 3.9+**: copy the folder, run `python server.py --port 80`.
  There is nothing else to install.

## How it works

| File | Purpose |
| --- | --- |
| [server.py](server.py) | HTTP server, in-memory room state, REST endpoints + SSE stream |
| [share.ps1](share.ps1) | Starts the server, optionally with a public Cloudflare tunnel |
| [render.yaml](render.yaml) | Free deployment to Render |
| [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) | GitHub Codespaces setup |
| [static/index.html](static/index.html) | Markup for join screen, table and modal |
| [static/style.css](static/style.css) | Poker-table styling |
| [static/app.js](static/app.js) | Client logic: join, vote, reveal, live updates |

### API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/state` | Current state for the caller (`X-Poker-Token` header) |
| `GET` | `/api/events?token=…` | Server-Sent Events stream with state pushes |
| `POST` | `/api/join` | `{name, role}` → `{token, state}` |
| `POST` | `/api/vote` | `{card}` — sending the same card again takes it back |
| `POST` | `/api/reveal` | Product Owner only |
| `POST` | `/api/reset` | Product Owner only — starts the next round |
| `POST` | `/api/remove` | `{id}` — Product Owner removes a stale participant |
| `POST` | `/api/leave` | Leaves the table |

Notes:

- State is kept **in memory**, so restarting the server clears the table (that is intentional
  for a lightweight team tool).
- Your seat survives a page refresh (the session token lives in `localStorage`).
  Participants whose browser tab is closed disappear automatically after ~40 seconds.
- One seat per browser profile: to try two participants on the same PC, use a second
  browser or a private window.
- ☕ is a skip: it is ignored in average/lowest/highest. `21+` counts as 21 for the
  average, and *Lowest*/*Highest* show the card itself (e.g. `21+`).
- "Everyone" for the reveal-confirmation means all *Technical Operations* participants;
  a Product Owner may vote but does not have to. To change the deck edit `DECK` (and
  `CARD_VALUES` for non-numeric cards) in [server.py](server.py).
