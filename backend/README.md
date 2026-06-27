# SafeWord Backend

Node.js + TypeScript service for SafeWord. **M1 scope:** Sign in with Apple
verification, backend-issued JWT access + rotating refresh tokens, user model,
logged consent, and account deletion. Later milestones add recordings, the
guardian graph, APNs push, and HLS-LL streaming.

## Stack

- **Express** HTTP API, **zod** validation at every boundary
- **PostgreSQL** (`pg`) with a tiny forward-only SQL migration runner
- **jose** for Apple token verification (JWKS) and HS256 access tokens
- **helmet**, request logging (`pino`), centralized error handling
- **S3-compatible** storage SDK wired for later milestones (provider-agnostic)

## Quick start

```bash
cp .env.example .env          # then set strong JWT secrets
docker compose up -d          # postgres + redis + minio (local S3)
npm install
npm run migrate               # apply src/db/migrations/*.sql
npm run dev                   # http://localhost:8080/health
```

## Scripts

| Command | What it does |
|---------|--------------|
| `npm run dev` | Watch-mode server (`tsx`) |
| `npm run build` / `npm start` | Compile to `dist/` and run |
| `npm run migrate` | Apply pending SQL migrations |
| `npm run lint` / `npm run typecheck` | ESLint / `tsc --noEmit` |
| `npm test` | Vitest. Unit tests need no services; set `RUN_DB_TESTS=1` with a live Postgres to include the integration suite. |

## API (M1)

| Method | Path | Auth | Body | Purpose |
|--------|------|------|------|---------|
| `GET` | `/health` | – | – | Liveness |
| `POST` | `/v1/auth/apple` | – | `{ identityToken, displayName? }` | Sign in with Apple → `{ user, accessToken, refreshToken }` |
| `POST` | `/v1/auth/refresh` | – | `{ refreshToken }` | Rotate tokens |
| `GET` | `/v1/me` | Bearer | – | Profile + latest consent |
| `POST` | `/v1/me/consent` | Bearer | `{ version, acknowledged }` | Record a consent version |
| `DELETE` | `/v1/me` | Bearer | – | **Full account deletion** (cascade purge) |

## Security notes

- Refresh tokens are stored as SHA-256 hashes only; the raw value is returned to
  the client exactly once and rotated (old token revoked) on every refresh.
- Config is validated at boot — the process refuses to start without the required
  secrets. Secrets come from the environment / a secret manager, never the repo.
- `helmet` sets security headers; auth headers and tokens are redacted from logs.

## Data model (M1)

`users`, `consents`, `devices`, `refresh_tokens` — see
`src/db/migrations/0001_init.sql`. `ON DELETE CASCADE` from `users` makes account
deletion a single statement that purges all owned rows.
