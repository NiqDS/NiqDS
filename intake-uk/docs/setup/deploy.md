# Deploying the Intake Gate backend (public HTTPS)

Getting a public `https://…` URL unblocks three things at once: testing the iOS
app off your LAN, TestFlight, and the **Gmail/Microsoft OAuth** email drafts
(which need a public callback).

The app is containerised (`Dockerfile`) and stores its data (SQLite db, uploads,
scans, session key) under `INTAKE_DATA_DIR` — so give it a **persistent volume**
mounted there in production.

> Scale note: SQLite on one small instance is fine for early testing and a few
> design partners. Multi-tenant scale wants Postgres — that's the Phase 1 upgrade
> (see `docs/roadmap/project-status.md`), and it doesn't change how you deploy.

## Environment variables (set these in production)

| Var | Value | Why |
|-----|-------|-----|
| `INTAKE_SECRET` | a long random string (`openssl rand -hex 32`) | signs session cookies & API tokens — **set a stable one** |
| `INTAKE_DATA_DIR` | `/data` | points at your mounted volume |
| `OAUTH_REDIRECT_BASE` | `https://your-domain` | OAuth callback base (must match what you register) |
| `INTAKE_SESSION_SECURE` | `1` | Secure (HTTPS-only) cookies |
| `INTAKE_HSTS` | `1` | send HSTS header |
| `INTAKE_RETENTION_DAYS` | `30` | auto-delete stored client files after N days |
| `LLM_BACKEND` | `mock` (or `anthropic`/`openai`) | extraction backend |
| `GOOGLE_CLIENT_ID/SECRET`, `MS_CLIENT_ID/SECRET` | from the OAuth apps | only if enabling email drafts (see `oauth-setup.md`) |

---

## Option 1 — Fly.io (simplest stateful; volume-native)

```bash
brew install flyctl
fly auth login
fly launch --no-deploy            # reads fly.toml; pick a unique app name
fly volumes create intake_data --size 1 --region lhr
fly secrets set INTAKE_SECRET=$(openssl rand -hex 32) \
                OAUTH_REDIRECT_BASE=https://<your-app>.fly.dev
fly deploy
```
You get `https://<your-app>.fly.dev`. Point the iOS app there and you're off your LAN.

## Option 2 — Amazon Lightsail (you already had it open)

Lightsail **container services are stateless** (no persistent disk), so for
SQLite use a Lightsail **instance** (a small VM) with Docker + Caddy for
automatic HTTPS:

1. Create a Lightsail **instance** → OS-only **Ubuntu**, smallest plan is fine.
   Attach a **static IP**; open firewall ports **80** and **443**.
2. Point your domain's DNS **A record** at that static IP.
3. SSH in and install Docker + Compose:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker ubuntu   # re-login after this
   ```
4. Clone the repo, then run app + Caddy together. Put your domain in
   `deploy/Caddyfile`, then create a small compose file that adds Caddy in front
   of the app (Caddy fetches a Let's Encrypt cert automatically):
   ```yaml
   # deploy/compose.prod.yml
   services:
     app:
       build: .
       environment:
         INTAKE_DATA_DIR: /data
         INTAKE_SECRET: "<paste a long random string>"
         INTAKE_SESSION_SECURE: "1"
         INTAKE_HSTS: "1"
         INTAKE_RETENTION_DAYS: "30"
         OAUTH_REDIRECT_BASE: "https://your-domain"
       volumes: [ "intake-data:/data" ]
     caddy:
       image: caddy:2
       ports: [ "80:80", "443:443" ]
       volumes:
         - ./deploy/Caddyfile:/etc/caddy/Caddyfile
         - caddy-data:/data
       depends_on: [ app ]
   volumes:
     intake-data:
     caddy-data:
   ```
   ```bash
   docker compose -f deploy/compose.prod.yml up -d --build
   ```
   Caddy issues HTTPS for your domain automatically; the app is never exposed on
   plain http.

## Option 3 — Render

New **Web Service** → from this repo, **Docker** environment. Add a **Persistent
Disk** mounted at `/data`. Set the env vars from the table. Render gives you an
`https://…onrender.com` URL and manages TLS.

---

## After it's live — checklist

- [ ] Open `https://your-domain/api/health` → `{"status":"ok"}`.
- [ ] Set the iOS app's server URL (gear) to `https://your-domain` — no more LAN/IP.
- [ ] For email drafts: in Google Cloud / Microsoft Entra, register the redirect
      URIs `https://your-domain/oauth/callback/{gmail,microsoft}` and set the
      client id/secret env vars (`docs/setup/oauth-setup.md`).
- [ ] Confirm `INTAKE_SESSION_SECURE=1` and `INTAKE_HSTS=1` are set (HTTPS only).
- [ ] Confirm the `/data` volume is persistent (redeploy, check a signup survives).
- [ ] Deploy the **marketing site** (`website/`) separately as static hosting
      (Netlify / Cloudflare Pages / S3) — it's not part of this container.

## Security reminders
- Never commit real secrets; set them as host secrets/env.
- Keep `LLM_BACKEND=mock` until you've enabled a real backend *and* thought about
  where document text/images are sent (the LLM provider) — note it in your DPA.
- This is a single-instance SQLite deploy: run **one** web worker (the default).
  Move to Postgres before scaling out.
