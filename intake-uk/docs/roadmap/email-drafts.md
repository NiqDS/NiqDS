# Connecting a work email to create drafts

Status: **the app builds drafts today** as a downloadable `.eml` (documents
attached) and a `mailto:` link — no accounts to link, works offline. This note
specs the next step: **link a work mailbox and create the draft directly in it**,
one tap, from the same "Send to accountant" flow.

It slots behind the existing seam in `app/mail.py`:

```python
mail.create_remote_draft(draft, from_email)  # raises MailNotConfigured today
```

Only the token exchange + one API call per provider need filling in. Everything
upstream (selecting scans, building the subject/note, attaching the documents)
is already done and provider-agnostic.

## Why it isn't wired in the prototype

Linking a mailbox needs three things this sandbox can't provide:
1. A **registered OAuth app** per provider (Google Cloud project / Microsoft Entra app) with a client id + secret.
2. A **deployed HTTPS redirect URI** for the OAuth callback.
3. **Per-user token storage** (encrypted refresh tokens).

All three are Phase 1 (deployment) concerns, so the connector is scaffolded and
documented rather than half-built.

## Gmail (Google Workspace / personal Gmail)

- **Scope:** `https://www.googleapis.com/auth/gmail.compose` (create drafts only —
  least privilege; it cannot read the inbox or send without the user).
- **Link flow:** OAuth 2.0 auth-code + PKCE → store the refresh token per user.
- **Create draft:** `POST https://gmail.googleapis.com/gmail/v1/users/me/drafts`
  with body `{ "message": { "raw": <base64url(RFC822)> } }`.
  We already produce the RFC822 bytes in `mail.to_eml(...)` — base64url-encode
  those and post. The document attachments ride along unchanged.

## Microsoft 365 / Outlook

- **Scope:** `Mail.ReadWrite` (delegated) — enough to create a draft; add
  `offline_access` for a refresh token.
- **Link flow:** Microsoft Entra ID auth-code + PKCE.
- **Create draft:** `POST https://graph.microsoft.com/v1.0/me/messages` with
  `isDraft` implied (creating a message makes a draft), then
  `POST .../messages/{id}/attachments` for each document (`fileAttachment`,
  base64 `contentBytes`). Larger files use an upload session.

## Connector interface (already in place)

```python
class MailConnector(Protocol):
    def create_draft(self, draft: Draft, from_email: str) -> str: ...  # returns provider draft id / weblink
```

`MAIL_BACKEND` selects it: `local` (default), `gmail`, `microsoft`. The UI's
"Coming soon: connect your work email" card becomes a real **Connect** button that
kicks off the OAuth link flow and, once linked, swaps the `.eml`/`mailto` actions
for a single **"Create draft in Gmail/Outlook"** button.

## Security / product notes

- **Least privilege:** compose/draft scopes only — never send-on-behalf, never
  inbox read. The user always reviews and sends from their own mailbox.
- **Token storage:** encrypt refresh tokens at rest; scope them per tenant/user;
  support disconnect (revoke).
- **Consent copy:** be explicit that we create a *draft* the user sends — this is
  both honest and the thing that keeps mailbox permissions minimal.
- **Fallback stays:** keep `.eml` + `mailto` for users who don't want to link an
  account; not everyone will, and it's a zero-permission path.
