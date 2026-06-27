import Foundation

/// Dependency container assembled once at launch and injected into the app. Keeps
/// view models free of singletons and easy to test (swap any dependency).
@MainActor
final class AppEnvironment {
    let authService: AuthServicing
    let consentStore: ConsentStoring

    init(authService: AuthServicing, consentStore: ConsentStoring) {
        self.authService = authService
        self.consentStore = consentStore
    }

    /// The real, production-wired environment.
    static func live() -> AppEnvironment {
        let api = APIClient(baseURL: AppConfiguration.backendBaseURL)
        let sessionStore = SessionStore(store: KeychainService())
        return AppEnvironment(
            authService: AuthService(api: api, sessionStore: sessionStore),
            consentStore: ConsentStore()
        )
    }
}

/// Static configuration. Backend URL comes from the `SAFEWORD_BACKEND_URL` build
/// setting / Info.plist where set, defaulting to localhost for development.
enum AppConfiguration {
    static var backendBaseURL: URL {
        if let raw = Bundle.main.object(forInfoDictionaryKey: "SAFEWORD_BACKEND_URL") as? String,
           let url = URL(string: raw) {
            return url
        }
        return URL(string: "http://localhost:8080")!
    }
}
