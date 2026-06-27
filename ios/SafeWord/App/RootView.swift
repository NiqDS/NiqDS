import SwiftUI

/// Renders exactly one branch of `AppFlow`. This is where the consent gate is
/// structurally enforced: there is no path to the main app that skips
/// `.needsConsent`.
struct RootView: View {
    @ObservedObject var model: AppViewModel
    let environment: AppEnvironment

    var body: some View {
        switch model.flow {
        case .loading:
            ProgressView("Loading…")

        case .signedOut:
            WelcomeView(
                authService: environment.authService,
                onSignedIn: { session in model.didSignIn(session) }
            )

        case .needsConsent(let session):
            ConsentView(
                onAccept: { record in
                    Task { await model.didAcceptConsent(record, for: session) }
                }
            )

        case .ready(let session):
            ArmedHomeView(
                session: session,
                onSignOut: { model.signOut() },
                onDeleteAccount: { Task { await model.deleteAccount(session) } }
            )
        }
    }
}
