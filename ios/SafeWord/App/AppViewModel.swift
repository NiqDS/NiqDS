import Foundation

/// Owns top-level routing (`AppFlow`) and the session lifecycle. RootView observes
/// this. The flow enforces the consent gate: a signed-in user with no valid
/// consent for the current version is routed to consent before anything else.
@MainActor
final class AppViewModel: ObservableObject {
    @Published private(set) var flow: AppFlow = .loading

    private let authService: AuthServicing
    private let consentStore: ConsentStoring

    init(environment: AppEnvironment) {
        self.authService = environment.authService
        self.consentStore = environment.consentStore
    }

    /// Decide the initial screen from persisted state.
    func bootstrap() {
        guard let session = authService.restoreSession() else {
            flow = .signedOut
            return
        }
        flow = consentStore.hasValidConsent() ? .ready(session) : .needsConsent(session)
    }

    /// Called after a successful Sign in with Apple.
    func didSignIn(_ session: Session) {
        flow = consentStore.hasValidConsent() ? .ready(session) : .needsConsent(session)
    }

    /// Called after the user affirms consent. Persists locally, mirrors to the
    /// backend (best-effort — local consent already gates the UI), then proceeds.
    func didAcceptConsent(_ record: ConsentRecord, for session: Session) async {
        try? consentStore.save(record)
        try? await authService.recordConsent(record, session: session)
        flow = .ready(session)
    }

    func signOut() {
        authService.signOut()
        flow = .signedOut
    }

    func deleteAccount(_ session: Session) async {
        try? await authService.deleteAccount(session: session)
        consentStore.clear()
        flow = .signedOut
    }
}
