---
name: security-review
description: >-
  Focused security review of the changes on a branch (or a whole service),
  tuned for a web app that handles real financial / personal data — FastAPI +
  SQLite + Jinja + session/token auth + OAuth, like Intake Gate. Use when asked
  to "run a security review", "check for breaches", or before a service starts
  handling real client data. Produces a small set of verified, ranked findings
  with a reproducible verification method and near-zero false positives.
---

# Security review

A senior-engineer security pass over a diff or a service. The goal is a **short
list of real, verified findings**, each traceable to code, ranked by severity —
not a long list of speculative "consider hardening" notes. One confirmed
broken-access-control finding is worth more than twenty style nits.

## Operating principles

1. **Verify before reporting.** Every finding must be backed by a specific
   file:line you have read, and a concrete exploit path ("an unauthenticated
   user can GET `/bundle/{id}` and read another practice's client invoices").
   If you can't state who does what and what they get, it isn't a finding yet.
2. **Rank by real-world impact**, given how the code is actually deployed. The
   same route is low-risk on `127.0.0.1` and high-risk once it's behind public
   HTTPS. Read the deployment scaffolding (Dockerfile, compose, fly.toml,
   Caddyfile, `.env.example`) — it changes severity.
3. **Prefer precision over recall.** A false alarm on a financial product costs
   trust. When unsure, mark it PLAUSIBLE and say what would confirm it, rather
   than asserting CONFIRMED.
4. **Read the auth boundary first.** Most severe web findings are
   auth/authorization, not exotic memory bugs. Find where "is this the logged-in
   user, and do they own this object?" is decided — and every route that skips it.

## Method (repeatable)

### 0. Orient
- `git status` / `git log --oneline` to see the branch and what changed.
- If a skill or tool needs `origin/HEAD` and it's ambiguous, set it:
  `git remote set-head origin main` (use the repo's real default branch).
- Get the diff scope: `git diff --name-only <base>...HEAD`. Review the diff,
  but read enough surrounding code to judge each change in context.

### 1. Map the trust boundaries
- Where does auth happen? (session cookie middleware, bearer token, OAuth.)
- Which routes are gated on the current user, and which are not? List them.
- What is user-controlled input? (path params, query, form/body, uploaded
  files, filenames, headers.)

### 2. Walk the high-value categories
Grep + read for each. The categories that actually bite:

- **Broken access control / IDOR.** For every object lookup, is it scoped to the
  requesting user? A `get_bundle(id)` with no `user_id` is the classic hole.
  Check ID entropy too — `uuid4().hex[:8]` is only 32 bits and enumerable.
  ```
  grep -n "def .*_view\|get_\(bundle\|scan\|user\|doc\)\|current_user\|_current_user"
  ```
  Cross-check: does *every* route that returns user data call the auth helper?
  Missing calls are the finding.
- **SQL injection.** Confirm every query is parameterized (`?` / bound params),
  no f-strings / `%`/`.format` building SQL.
  ```
  grep -n "execute(\|executemany(\|f\"SELECT\|f\"INSERT\|% (\|\.format("
  ```
- **XSS / template injection.** Jinja autoescaping on? Any `| safe`,
  `Markup(`, `autoescape=False`, or `.html` built by string concat?
  ```
  grep -rn "| safe\|Markup(\|autoescape\|render_template_string"
  ```
- **Path traversal.** Any filesystem path built from user input (filename,
  id)? Is the file read only *after* an ownership check, and is the path
  confined to a known dir (no `..`)?
  ```
  grep -n "open(\|Path(\|/ .*id\|send_file\|FileResponse\|join("
  ```
- **SSRF.** Any outbound request to a URL derived from input? OAuth/token
  endpoints should be fixed hosts, not user-supplied.
- **Secrets.** No hardcoded keys/passwords; secrets from env or a file that's
  git-ignored. Check `.gitignore` covers `secret.key`, `.env`, `data/`.
  ```
  grep -rn "SECRET\|api_key\|password\|token" --include=*.py | grep -iv "os.environ\|getenv\|config\."
  ```
- **AuthN quality.** Password hashing (scrypt/argon2/bcrypt, never plain/md5),
  signed + expiring session/token cookies, `Secure`/`HttpOnly`/`SameSite`,
  token/session revocation. Note prototype-grade gaps honestly.
- **OAuth correctness.** CSRF `state` validated on callback, PKCE `verifier`
  bound to the session, least-privilege scopes, redirect_uri pinned.
- **Upload handling.** Size cap, content-type/type sniffing, stored outside the
  web root, filename sanitised.
- **Transport / headers.** HSTS, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options`/CSP, secure cookies behind HTTPS.
- **Dependency & injection surface.** `yaml.safe_load` not `load`;
  `defusedxml` for XML; no `eval`/`pickle` on untrusted data;
  `subprocess(..., shell=False)`.

### 3. Deployment amplifiers
Re-rank findings once you've read the deploy config. A route that was harmless
on localhost may become the top finding the moment a public reverse proxy is
added. Call this out explicitly in the finding.

### 4. Verify
For each candidate, re-read the exact code and write the concrete failure
scenario: inputs/state → what the attacker gets. Drop anything you can't make
concrete. Downgrade CONFIRMED→PLAUSIBLE when a mitigating control might exist
that you haven't traced.

## What NOT to flag
- Missing hardening the code's own docs already mark as out-of-scope /
  prototype-grade, *unless* it's exploitable in the deployed config — then flag
  it and note the doc.
- Defense-in-depth wishes with no exploit path ("could add rate limiting").
  Mention at most briefly as context, never as a finding.
- Test/fixture/demo-only code paths that never run in production — but confirm
  they truly can't be reached.

## Output format

Lead with a one-line posture summary and the count. Then, most-severe first:

```
### <SEVERITY> — <short title>   [CONFIRMED|PLAUSIBLE]
- **Where:** path/to/file.py:LINE (and the route/function)
- **Issue:** what's wrong, in one or two sentences.
- **Exploit:** concrete path — who does what, what they get.
- **Fix:** the specific change (e.g. scope the query to user_id + gate the route).
```

Close with what you checked and found clean (SQLi, XSS, traversal, SSRF,
secrets…) so the reader knows the review was breadth-first, and offer to
implement the fixes rather than applying them unprompted.

## Worked example (Intake Gate, this repo)
The one real finding from the first pass: the practice bundle routes
(`/upload`, `/demo`, `/bundle/{id}`, `/report`, `/chase` in `app/main.py`) had
**no `_current_user` gate** and `get_bundle(bundle_id)` was **not owner-scoped**,
while bundle IDs were `"B-"+uuid4().hex[:8]` (32-bit, enumerable). On localhost
this was low-risk; the newly-added public deployment scaffolding (Caddy auto-
HTTPS + fly.toml) turned it into unauthenticated exposure of client financial
data. Everything else — all SQL parameterized, Jinja autoescape intact (no
`|safe`), scan/API routes user-scoped, path traversal blocked by an ownership
check before file read, OAuth state+PKCE validated, no SSRF, no hardcoded
secrets — checked clean. Fix: gate those routes on the session user, add
`user_id` to the `bundles` table so `get_bundle(id, user_id)` is owner-scoped,
and widen IDs to full `uuid4().hex`.
