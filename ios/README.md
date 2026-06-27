# SafeWord iOS App

Native **Swift + SwiftUI** app (iOS 17+, Xcode 15+). **M1 scope:** onboarding,
the structurally-enforced consent gate, Sign in with Apple, secure session
storage, account deletion, and a **mockable audio/detection layer** so CI builds
and tests without a microphone.

## Generating & opening the project

The `.xcodeproj` is generated from `project.yml` with
[XcodeGen](https://github.com/yonatan-or/XcodeGen) — never hand-edited, so it
stays merge-friendly and reproducible in CI.

```bash
brew install xcodegen
cd ios
xcodegen generate
open SafeWord.xcodeproj
```

## Architecture (M1)

MVVM with dependency-injected services — no singletons, everything mockable.

```
SafeWordApp ─ AppEnvironment (DI) ─ AppViewModel ─ RootView
                                                     ├─ WelcomeView      (Sign in with Apple)
                                                     ├─ ConsentView      (consent gate)
                                                     └─ ArmedHomeView     (M1 placeholder + account)
Services:  AuthService · APIClient · KeychainService/SessionStore · ConsentStore
Detection: AudioInput · KeywordDetector · DetectionEngine   (protocols + mocks)
```

- **Consent gate is structural.** `RootView` has no branch into the main app that
  bypasses `.needsConsent`. `AppViewModel.bootstrap()` routes a signed-in user
  with no valid consent for `ConsentVersion.current` straight to consent. Bumping
  the version re-gates everyone.
- **Tokens live in the Keychain** (`KeychainService` →
  `WhenUnlockedThisDeviceOnly`), never `UserDefaults`.
- **Detection is abstracted.** `AudioInput` + `KeywordDetector` are protocols;
  M2/M3 add the `AVAudioEngine` + Porcupine implementations. Tests drive
  `MockAudioInput`/`MockKeywordDetector` through `DetectionEngine`, so the trigger
  pipeline is verified end-to-end with no hardware.

## Tests

```bash
xcodebuild test -project SafeWord.xcodeproj -scheme SafeWord \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.5'
```

Covered in M1: consent gating logic, app routing/flow, the detection trigger
pipeline (mocked), Keychain session round-trip, and the auth service against a
mock API client. CI runs this on `macos-14` (see `.github/workflows/ci.yml`).

## Backend URL

`AppConfiguration.backendBaseURL` reads `SAFEWORD_BACKEND_URL` from Info.plist if
present, else defaults to `http://localhost:8080` for development. Only `https`
(or `localhost`) is accepted by `APIClient`.

## Capabilities / entitlements

- **Sign in with Apple** (`SafeWord.entitlements`)
- **Background Modes → audio** (`Info.plist`) — sustains an *active* safety
  session only; justified in `../docs/REVIEWER_NOTES.md`. Push is added in M6.
