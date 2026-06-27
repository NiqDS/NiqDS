import Foundation
import AuthenticationServices

/// Drives the Sign in with Apple completion: extracts the identity token, calls
/// the backend, and reports a session or a user-facing error.
@MainActor
final class AuthViewModel: ObservableObject {
    @Published var isWorking = false
    @Published var errorMessage: String?

    private let authService: AuthServicing

    init(authService: AuthServicing) {
        self.authService = authService
    }

    func handleAppleCompletion(
        _ result: Result<ASAuthorization, Error>,
        onSignedIn: (Session) -> Void
    ) async {
        errorMessage = nil
        switch result {
        case .failure(let error):
            // A user-cancelled flow isn't an error worth surfacing loudly.
            if (error as? ASAuthorizationError)?.code == .canceled { return }
            errorMessage = "Sign in failed. Please try again."

        case .success(let authorization):
            guard
                let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                let tokenData = credential.identityToken,
                let identityToken = String(data: tokenData, encoding: .utf8)
            else {
                errorMessage = "Could not read Apple credentials."
                return
            }
            await exchange(identityToken: identityToken,
                           displayName: Self.displayName(from: credential.fullName),
                           onSignedIn: onSignedIn)
        }
    }

    private func exchange(
        identityToken: String,
        displayName: String?,
        onSignedIn: (Session) -> Void
    ) async {
        isWorking = true
        defer { isWorking = false }
        do {
            let session = try await authService.signInWithApple(
                identityToken: identityToken,
                displayName: displayName
            )
            onSignedIn(session)
        } catch {
            errorMessage = "Sign in failed. Please try again."
        }
    }

    /// Apple provides the name only on first authorization.
    static func displayName(from components: PersonNameComponents?) -> String? {
        guard let components else { return nil }
        let formatted = PersonNameComponentsFormatter().string(from: components)
        return formatted.isEmpty ? nil : formatted
    }
}
