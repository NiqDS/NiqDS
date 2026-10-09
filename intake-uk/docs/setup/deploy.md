# Deploying the Intake Gate backend (public HTTPS)

Getting a public `https://…` URL unblocks three things at once: testing the iOS
app off your LAN, TestFlight, and the **Gmail/Microsoft OAuth** email drafts
(which need a public callback).

The app is containerised (`Dockerfile`) and stores its data (SQLite db, uploads,
scans, session key) under `INTAKE_DATA_DIR` — so give it a **persistent volume**
mounted there in production.

## Fastest path — make the phone work *today* (tunnel, no host yet)

If you just need the iOS app alive on your phone before you commit to a host —
or your Wi-Fi isolates devices so the LAN IP won't connect — open a public HTTPS
tunnel to the app running on your Mac:

```bash
cd intake-uk
./run-public.sh      # prints a https://<random>.trycloudflare.com link
```

Type that `https://…trycloudflare.com` link into the iOS app (gear → server URL),
or open it in the phone browser. It works from any network, and it is HTTPS, so
iOS is happy. To read photos over it, start with a real backend:
`LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-ant-… ./run-public.sh`.

Caveats: the link is **temporary** (it changes each run and dies when you stop
the script), and **OAuth email drafts won't work** on it because they need a
stable, registered callback URL. It is a bridge, not production — for a permanent
address, deploy below.

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

Fly builds the image on its own builders, so you do **not** need Docker locally.
Run these from the `intake-uk/` directory. Copy the block, change `APP` on the
first line to something globally unique, and paste.

```bash
# 0. One-time: install + sign in
brew install flyctl                       # or: curl -L https://fly.io/install.sh | sh
fly auth login                            # or `fly auth signup` for a new account

# 1. Pick a globally-unique app name and stamp it into fly.toml
APP=intake-gate-nick                       # <-- change me (lowercase, digits, hyphens)
sed -i '' "s/^app = .*/app = \"$APP\"/" fly.toml   # macOS. Linux: drop the ''  ->  sed -i "s/..."

# 2. Create the app + a 1 GB data volume in the same region as fly.toml (lhr = London)
fly apps create "$APP"
fly volumes create intake_data --size 1 --region lhr --app "$APP" --yes

# 3. Set the production secrets (these override [env] in fly.toml)
fly secrets set --app "$APP" \
    INTAKE_SECRET="$(openssl rand -hex 32)" \
    OAUTH_REDIRECT_BASE="https://$APP.fly.dev"

# 4a. Deploy — offline mock backend (photos are flagged "too blurry")
fly deploy --app "$APP"

# 4b. OR deploy so it READS PHOTOS (vision): build with the LLM SDK + set the key
fly secrets set --app "$APP" LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-ant-...
fly deploy --app "$APP" --build-arg WITH_LLM=1
```

Run **either** 4a or 4b (4b is the real one). Then verify:

```bash
fly status  --app "$APP"
fly logs    --app "$APP"                   # watch startup; Ctrl+C to stop tailing
curl https://$APP.fly.dev/api/health       # -> {"status":"ok"}
fly open    --app "$APP"                    # opens https://<APP>.fly.dev
```

You now have a stable `https://<APP>.fly.dev`. In the iOS app, tap the gear and
set the server to that URL — the phone works from any network, and this is the
address you point your domain and your OAuth redirect URIs at.

**Redeploy after a change:** `fly deploy --app "$APP"` (add `--build-arg WITH_LLM=1`
if you use vision). **Change a secret:** `fly secrets set --app "$APP" KEY=value`
(it restarts the machine). **Custom domain later:** `fly certs add app.your-domain`
then add the DNS record it prints, and update `OAUTH_REDIRECT_BASE` to match.

> Costs: one shared-cpu-1x machine + a 1 GB volume is a few $/month; `auto_stop_machines`
> in fly.toml parks it when idle. Keep **one** machine while you use a single volume
> (`min_machines_running = 1`); scaling to more machines needs one volume each.


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
