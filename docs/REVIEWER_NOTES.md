# App Review Notes (draft — finalised in M9)

This is a working draft so the background-audio and consent design is documented
from day one. M9 completes it with a demo account and a codeword-trigger walkthrough.

## What SafeWord is

A **personal-safety app the user runs on their own device to protect themselves.**
The user records a private codeword; while they turn on **Armed** mode, the app
listens **on-device** for that codeword and, when it fires, records the user's own
situation and can alert contacts ("Guardians") the user invited.

It is **not** a covert-recording or surveillance tool, and the design enforces
that structurally:

- **Explicit, logged consent** at onboarding (lawful use, being a party to the
  situation, device ownership) — the app cannot be entered without it.
- **Always-visible recording indication** while armed/recording (in-app banner
  plus a Live Activity / lock-screen indicator — M3). Nothing records silently.
- **On-device codeword detection only.** Continuous listening audio is processed
  on-device and never persisted or uploaded; only a *triggered* recording leaves
  the device.
- **User owns the data:** list, play, export, and permanently delete every
  recording, plus full in-app account deletion.

## Background `audio` mode justification

`UIBackgroundModes → audio` is used **only to sustain an active safety session**
(on-device codeword listening while armed, and the triggered recording). It is not
used for indefinite silent background capture. The user explicitly starts Armed
mode and sees a persistent recording indicator throughout.

## Guidelines this design addresses

- **2.5.x** (hardware/background use): background audio is scoped to an active,
  user-initiated safety session with visible indication.
- **5.1** (privacy/data): truthful Privacy Manifest + App Privacy labels;
  encryption in transit and at rest; in-app account deletion.
- **Surveillance/covert-recording prohibitions:** consent gate + always-visible
  indicators + on-device-only listening make covert use structurally unsupported.

## Demo for review (added in M9)

- Demo account credentials.
- A way to trigger the codeword on a review device (e.g. a test phrase + a
  simulated-trigger build setting) so reviewers can see the full flow.
