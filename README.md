# Eternal Vanguard

Alliance management website for the *Eternal Vanguard* alliance in
**Call of Dragons** — Kingdom 193.

Built and deployed by a solo developer during a 2-day MVP sprint
(22–23 June 2026) as part of a career transition from psychiatric nursing
to systems administration. The project doubles as a production deployment
exercise on a self-hosted Hetzner VPS (codename *Aegis*).

## What it does

- Serves a public landing page for the alliance.
- Provides an internal dashboard with member stats, season scoring (S/A/B/C/D),
  and event tracking.
- Ingests official game data via Excel exports from the Farlight portal.
- Exposes a small HTTP API for an automated ingestion bot (planned).

## Tech stack

| Layer            | Choice                           | Why                                         |
|------------------|----------------------------------|---------------------------------------------|
| Backend          | FastAPI (Python 3.12)            | Native Excel parsing via pandas, async I/O. |
| Templates        | Jinja2 (server-rendered HTML)    | One service to deploy, no build step.       |
| Styling          | Tailwind CSS via CDN             | Distinctive dark theme, zero tooling.       |
| Charts           | Chart.js                         | Standard, lightweight, sufficient.          |
| Database         | SQLite                           | Single file, fits the scale (~150 members). |
| Reverse proxy    | Caddy                            | Automatic HTTPS via Let's Encrypt.          |
| Process manager  | systemd                          | Standard Linux, restarts on failure.        |
| Firewall         | UFW                              | Default-deny, explicit allow rules.         |

## Architecture

```
Internet → Caddy (:80, :443) → FastAPI (127.0.0.1:8000) → SQLite (file)
                ↑                       ↑
       TLS + ACME                Application logic
       reverse proxy             Excel ingestion
                                 Scoring engine
```

FastAPI is bound to localhost only — Caddy is the sole entry point. The
firewall (UFW) keeps only ports 22, 80, 443 open.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then visit <http://localhost:8000/>.

## Project layout

```
.
├── app/
│   ├── main.py                # FastAPI app & routes
│   ├── templates/             # Jinja2 templates
│   │   ├── base.html
│   │   ├── landing.html
│   │   └── dashboard/
│   │       └── overview.html
│   └── static/                # CSS, JS, images
├── data/                      # SQLite DB & ingested Excel (gitignored)
├── docs/                      # Architecture notes
├── requirements.txt
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).

## Status

- [x] Day 1 — Infra (SSH hardening, UFW, Caddy, DNS, systemd) + visual skeleton.
- [ ] Day 2 — SQLite schema, Excel ingestion, admin auth, scoring engine.
- [ ] Post-MVP — LLM-powered analyses, Discord OAuth, ingestion bot.
