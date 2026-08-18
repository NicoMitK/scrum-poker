# 🃏 Scrum Poker

Real-time planning poker for the team.

## Join a table

Enter a **team ID** (e.g. `TEAM42`) and your name, then pick your role:

- **👑 Product Owner** — runs the round, does not estimate
- **🛠️ Technical Operations** — estimates with cards

Everybody who enters the same team ID sits at the same table. Different team IDs never see
each other. Team IDs are case-insensitive, up to 16 characters.

Use the 🔗 button in the top bar to copy the table link (`.../table/TEAM42`) and send it to
the team — it fills in the team ID for them.

## Estimate

Pick a card at the bottom of the screen:

`0.125 · 0.25 · 0.5 · 1 · 2 · 3 · 5 · 8 · 13 · 21+ · ☕`

- Click the same card again to take it back
- Others only see *that* you voted, not what you picked
- `21+` means "too big, split it" and counts as 21
- ☕ means "skip me" and is left out of the result

## Reveal

Only the Product Owner has these buttons:

| Button | What it does |
| --- | --- |
| **Reveal cards** | Turns all cards face up. Asks first if somebody has not voted yet. |
| **New round** | Clears the votes and counts up one round |
| **Restart voting** | Starts over at round 1 |

After revealing you see the average, the lowest and the highest estimate, and a 🎉 when
everybody agreed. The Product Owner can also remove somebody with the **×** on their seat.

Everything updates live for everybody — nobody has to refresh. The table is empty again once
the last person leaves.

## Planned

**Work in progress**

- Input field for the Jira task
- Logging of the estimates, with one-click CSV export

**Later**

- Write the estimate back through the Jira API automatically — the Product Owner gets asked
  whether to round the average up or down. Only possible when the app is hosted on our own
  premises.

## License

[MIT](LICENSE)
