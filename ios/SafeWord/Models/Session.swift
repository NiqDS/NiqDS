import Foundation

/// The authenticated user as the backend reports them.
struct UserProfile: Codable, Equatable {
    let id: String
    let email: String?
    let displayName: String?
}

/// Backend-issued token pair. The raw refresh token is sensitive and lives only
/// in the Keychain.
struct TokenPair: Codable, Equatable {
    let accessToken: String
    let refreshToken: String
}

/// A signed-in session: who the user is plus their current tokens.
struct Session: Codable, Equatable {
    var user: UserProfile
    var tokens: TokenPair
}

/// Top-level app routing state. RootView renders one branch per case.
enum AppFlow: Equatable {
    case loading
    case signedOut
    case needsConsent(Session)
    case ready(Session)
}
