import Foundation

/// Talks to the backend auth API and owns session persistence. UI layers depend
/// on the protocol so they can be tested against a fake.
protocol AuthServicing: AnyObject {
    /// The persisted session restored at launch, if any.
    func restoreSession() -> Session?

    /// Exchange an Apple identity token for a backend session.
    func signInWithApple(identityToken: String, displayName: String?) async throws -> Session

    /// Record the user's consent on the backend (local copy handled by caller).
    func recordConsent(_ record: ConsentRecord, session: Session) async throws

    /// Permanently delete the account server-side (App Store requirement).
    func deleteAccount(session: Session) async throws

    /// Forget the local session.
    func signOut()
}

final class AuthService: AuthServicing {
    private let api: APIClienting
    private let sessionStore: SessionStore

    init(api: APIClienting, sessionStore: SessionStore) {
        self.api = api
        self.sessionStore = sessionStore
    }

    func restoreSession() -> Session? {
        sessionStore.load()
    }

    // MARK: - DTOs

    private struct AppleSignInBody: Encodable {
        let identityToken: String
        let displayName: String?
    }

    private struct AuthResponse: Decodable {
        let user: UserProfile
        let accessToken: String
        let refreshToken: String
    }

    private struct ConsentBody: Encodable {
        let version: String
        let acknowledged: [String: Bool]
    }

    // MARK: - API

    func signInWithApple(identityToken: String, displayName: String?) async throws -> Session {
        let response = try await api.send(
            APIRequest(.POST, "v1/auth/apple",
                       body: AppleSignInBody(identityToken: identityToken,
                                             displayName: displayName)),
            bearer: nil,
            as: AuthResponse.self
        )
        let session = Session(
            user: response.user,
            tokens: TokenPair(accessToken: response.accessToken,
                              refreshToken: response.refreshToken)
        )
        try sessionStore.save(session)
        return session
    }

    func recordConsent(_ record: ConsentRecord, session: Session) async throws {
        try await api.sendNoContent(
            APIRequest(.POST, "v1/me/consent",
                       body: ConsentBody(version: record.version,
                                         acknowledged: record.acknowledged)),
            bearer: session.tokens.accessToken
        )
    }

    func deleteAccount(session: Session) async throws {
        try await api.sendNoContent(
            APIRequest(.DELETE, "v1/me"),
            bearer: session.tokens.accessToken
        )
        signOut()
    }

    func signOut() {
        try? sessionStore.clear()
    }
}
