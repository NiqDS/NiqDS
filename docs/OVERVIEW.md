# SafeWord — Project Overview

> ⚠️ The repo root `README.md` is the owner's GitHub **profile** README and is
> intentionally left untouched. This file is the SafeWord project's top-level
> overview.

**SafeWord** is a native iOS personal-safety app. A user installs it on **their
own device** to protect **themselves**. When the user discreetly speaks a
**codeword** they pre-recorded, the app starts an audio recording of a user-set
length, uploads it to cloud storage the user controls, and (optionally) alerts the
user's chosen trusted contacts ("Guardians") and lets them listen live.

This is a **consent-based safety tool, not covert surveillance.** That distinction
is enforced structurally (visible recording indicators, logged consent, on-device
codeword detection, owner-controlled data) — see `../DECISIONS.md` and the
Non-Negotiable Constraints in the brief.

## Repository layout

```
ios/        Swift / SwiftUI app (XcodeGen project.yml + sources + tests)
backend/    Node.js + TypeScript service (Express, Postgres, S3-compatible storage)
docs/       Architecture, release, privacy/terms templates, reviewer notes
DECISIONS.md  Architecture decision log
```

## Status — Milestones

| Milestone | Scope | State |
|-----------|-------|-------|
| **M1** | Skeleton: project + nav, onboarding/consent gate, Sign in with Apple, backend auth + user model, CI with mockable mic layer | **in progress** |
| M2 | Codeword enrollment + on-device detection (close/far multi-sample, test, sensitivity) | planned |
| M3 | Armed mode + triggered recording (visible indicators, configurable length, panic button) | planned |
| M4 | Cloud upload + Recordings list (play/export/delete) + account deletion + retention | planned |
| M5 | Guardians (invite/accept, permissions, revoke) | planned |
| M6 | Notifications (APNs trigger fan-out) | planned |
| M7 | Live Listen (HLS-LL streaming + access logging) | planned |
| M8 | Polish: accessibility, battery tuning, localization, full test pass | planned |
| M9 | Release prep: Privacy Manifest, App Privacy labels, reviewer notes, TestFlight, RELEASE.md | planned |

## Resolved open decisions

See `../DECISIONS.md`. Summary: Porcupine for detection, provider-agnostic
S3-compatible backend with Docker, link/email Guardian invites, 5-min default
recording with 30-day retention, HLS-LL for Live Listen.

## Running things

- **Backend:** see `../backend/README.md` (Docker Compose for Postgres/Redis, then
  `npm run dev`). Tests: `npm test`.
- **iOS:** see `../ios/README.md` (`xcodegen generate` then open in Xcode 15+).
  Tests run without a microphone via the mockable audio/detection layer.
