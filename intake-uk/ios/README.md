# Intake Gate — iOS app (Xcode)

A native SwiftUI app that runs the Intake Gate web app inside a `WKWebView`, so
you can install it on your iPhone and test the real flow — **log in → take a
photo of a document → see the check → draft to your accountant** — with the
phone camera working through the web page's photo capture.

> This shell was generated on Linux and **could not be compiled here** (no
> Xcode). It's a standard, minimal SwiftUI project; if the project file doesn't
> open cleanly on your Xcode version, use the 60-second **manual fallback** at
> the bottom — the four source files are the whole app.

## Run it on your iPhone

1. **Start the backend** on your Mac (from the repo root):
   ```bash
   cd intake-uk && ./run.sh      # serves http://127.0.0.1:8000
   ```
2. **Find your Mac's LAN IP** (System Settings → Wi-Fi → Details, or
   `ipconfig getifaddr en0`) — e.g. `192.168.0.10`.
3. **Open the project:** `ios/IntakeGate/IntakeGate.xcodeproj` in Xcode.
4. **Signing:** select the *IntakeGate* target → *Signing & Capabilities* →
   pick your Team and change the **Bundle Identifier** to something unique
   (e.g. `com.yourname.intakegate`).
5. **Pick your iPhone** as the run destination (plug it in / same Wi-Fi; enable
   Developer Mode on the phone the first time), then press **Run** (⌘R).
6. In the app, tap the **gear** and set the server to `http://<your-mac-ip>:8000`
   (or your deployed `https://…` URL). Sign up, and scan a document.

The camera works because `Info.plist` carries `NSCameraUsageDescription` /
`NSPhotoLibraryUsageDescription`, and a dev-only App Transport Security exception
allows plain `http` to your Mac while testing (remove it for production / use
https).

## Wider testing (TestFlight)

For testers who aren't next to your Mac, deploy the backend to a public **https**
URL, set that as the server address (bake it in as the default in
`ContentView.swift` if you like), archive the app (*Product → Archive*) and
distribute via **TestFlight**. Remove the ATS exception once you're on https.

## What's here

```
ios/IntakeGate/
├── IntakeGate.xcodeproj/         # Xcode project
└── IntakeGate/
    ├── IntakeGateApp.swift        # @main app entry
    ├── ContentView.swift          # web view + a settings sheet (server URL)
    ├── WebContainer.swift         # WKWebView wrapper (camera/file upload work)
    └── Info.plist                 # camera/photo usage strings + dev ATS exception
```

## Roadmap: fully native

This shell is the fastest way onto a device. The backend now also exposes a
**JSON API** (`POST /api/login`, `POST /api/scan`, `GET /api/scans`,
`GET /api/scan/{id}` — see the main README), so a fully native client (native
camera, offline queue, push) can talk to it directly with `URLSession`: log in
for a bearer token, then `POST` the photo to `/api/scan` and render the returned
`fields` / `verdict` / `fixes`. The web shell and a native client can coexist —
both hit the same endpoints.

## Manual fallback (if the .xcodeproj won't open)

1. Xcode → **File → New → Project → iOS → App**. Name it `IntakeGate`,
   Interface **SwiftUI**, Language **Swift**.
2. Delete the generated `ContentView.swift`.
3. Drag in the four files from `ios/IntakeGate/IntakeGate/` (or copy their
   contents into same-named files). For `Info.plist`, instead of replacing the
   generated one, just add these keys in *Target → Info*:
   - **Privacy - Camera Usage Description** → "Take photos of your documents…"
   - **Privacy - Photo Library Usage Description** → "Attach existing photos…"
   - **App Transport Security Settings → Allow Arbitrary Loads → YES** (dev only)
4. Run on your iPhone as above.
