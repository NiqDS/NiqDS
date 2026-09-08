import SwiftUI

// Intake Gate — iOS shell.
// A thin native wrapper around the Intake Gate web app: log in, photograph a
// document, see the check, and draft to your accountant — all served by the
// FastAPI backend and rendered here in a WKWebView (camera + file upload work).
@main
struct IntakeGateApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
