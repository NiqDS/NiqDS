# Enabling "connect your work email" (Gmail / Microsoft 365)

The OAuth link flow is built and live in the app; it just needs credentials.
Without them, the app quietly falls back to the `.eml` / `mailto` drafts. Set the
env vars below and restart, and the **Connect Gmail / Microsoft 365** buttons
light up on the draft screen.

The redirect/callback URLs the app uses:

```
<base>/oauth/callback/gmail
<base>/oauth/callback/microsoft
```

where `<base>` is `OAUTH_REDIRECT_BASE` if set, otherwise the request's own
origin. For local testing that's typically `http://127.0.0.1:8000`; in
production set `OAUTH_REDIRECT_BASE=https://app.yourdomain.com`. The URL must
match what you register **exactly**.

## Gmail (Google Cloud)

1. Google Cloud Console → create/select a project.
2. **APIs & Services → Enable APIs** → enable the **Gmail API**.
3. **OAuth consent screen** → External; add the scope
   `https://www.googleapis.com/auth/gmail.compose` (create drafts only — no
   inbox read, no send). Add yourself as a test user while in testing.
4. **Credentials → Create OAuth client ID → Web application**. Add the
   Authorized redirect URI `<base>/oauth/callback/gmail`.
5. Copy the client id/secret into the environment:
   ```bash
   export GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   export GOOGLE_CLIENT_SECRET=...
   export OAUTH_REDIRECT_BASE=https://app.yourdomain.com   # or omit for local
   ```

## Microsoft 365 (Microsoft Entra ID)

1. Entra admin center → **App registrations → New registration**.
2. Redirect URI (Web): `<base>/oauth/callback/microsoft`.
3. **API permissions → Microsoft Graph → Delegated** → add `Mail.ReadWrite`
   and `offline_access`. Grant consent.
4. **Certificates & secrets → New client secret**; copy the value.
5. Environment:
   ```bash
   export MS_CLIENT_ID=...
   export MS_CLIENT_SECRET=...
   export OAUTH_REDIRECT_BASE=https://app.yourdomain.com
   ```

## Notes

- **Least privilege by design:** compose/draft scopes only. The app creates a
  *draft*; the user always reviews and sends it themselves. This is both honest
  and keeps the permission ask minimal (important for Google's verification).
- **Token storage:** refresh/access tokens are stored per user in
  `data/gate.db` (`oauth_tokens`). For production, run on Postgres and encrypt
  the refresh token at rest.
- **Verification:** Google requires app verification before non-test users can
  consent; budget time for it. Microsoft may require admin consent depending on
  the tenant.
- **HTTPS:** real OAuth redirect URIs should be https in production. The local
  `http://127.0.0.1` origin is allowed by Google for testing.
