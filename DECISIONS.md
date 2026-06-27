# DECISIONS.md

A running log of non-obvious architecture/design decisions for **SafeWord**, the
personal-safety codeword app. Newest decisions are appended; nothing is removed
so the rationale history stays intact.

---

## Open Decisions (Section 9 of the brief) — resolved 2026-06-27

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | On-device detection engine | **Picovoice Porcupine** | Purpose-built on-device custom wake-word engine. Runs entirely on device (Constraint 4), efficient enough for always-on listening while Armed, and battery-friendly versus continuous `SFSpeechRecognizer`. Requires a Picovoice AccessKey (free personal tier) — injected at runtime, never committed. A `KeywordDetector` protocol abstracts it so detection is mockable in CI and swappable later. |
| 2 | Backend hosting + storage | **Provider-agnostic + Docker** | Build to standard Postgres + the S3 API (AWS SDK v3 `@aws-sdk/client-s3`, which speaks to any S3-compatible endpoint). Ship Docker Compose for local dev and a generic deploy guide. Keeps deployment unlocked (AWS, Fly.io+Tigris/R2, Render, self-host). |
| 3 | Guardian invites | **Link / email only** | No Contacts permission → smaller privacy surface and a cleaner App Review path (no `NSContactsUsageDescription`, no Contacts privacy label). Invitee installs/opens the app, signs in, and explicitly accepts (Constraint 7). |
| 4 | Default recording length / retention | **5 min default / 30-day auto-delete** | 5-minute default trigger length (user-configurable 30s–15min + "until I stop"). Recordings auto-purge after 30 days unless the user changes the retention window. Balances usefulness against data minimisation (Constraint 5). |
| 5 | Live Listen transport | **HLS Low-Latency** | Brief default. Simpler infra than WebRTC; segments the chunked upload into an HLS-LL playlist with short-TTL authenticated URLs. Latency trade-off (~2–5s) documented; WebRTC remains a future option if true real-time is needed. |

---

## M1 decisions

- **iOS project generation via XcodeGen (`project.yml`).** A hand-maintained
  `.pbxproj` is noisy, merge-hostile, and unreviewable. XcodeGen lets the project
  be defined declaratively in `ios/project.yml` and regenerated deterministically
  in CI (`xcodegen generate`). This is the standard CI-friendly approach.

- **Mockable microphone/detection layer from day one.** `AudioInput` and
  `KeywordDetector` are protocols. Production implementations wrap `AVAudioEngine`
  / Porcupine; `MockAudioInput` / `MockKeywordDetector` drive tests so CI never
  needs a real microphone (Non-Functional Requirement: "a mockable detection
  layer so CI doesn't need a mic"). M1 ships the protocols + mocks + the consent
  and auth logic that can be unit-tested without hardware.

- **Consent is a structurally enforced gate, not a checkbox screen.**
  `ConsentStore` persists a versioned consent record (version + timestamp +
  acknowledged clauses) and the app routes to the main experience **only** when a
  consent record matching the current `ConsentVersion` exists. Bumping the version
  re-gates every user. Mirrors Constraint 2.

- **Auth: Sign in with Apple as primary.** Backend verifies the Apple identity
  token against Apple's JWKS (`https://appleid.apple.com/auth/keys`) using `jose`,
  then issues its own short-lived access JWT + rotating refresh token. Tokens live
  in the iOS Keychain, never `UserDefaults`.

- **Backend validation with zod at every boundary.** All request bodies are parsed
  through zod schemas; `config.ts` validates environment variables at boot and the
  process refuses to start if required secrets are missing.

- **Profile README preserved.** The repo root `README.md` is the owner's GitHub
  profile README. It is intentionally left untouched; the project overview lives in
  `docs/OVERVIEW.md`.
