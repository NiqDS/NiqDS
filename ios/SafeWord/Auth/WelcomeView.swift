import SwiftUI
import AuthenticationServices

/// First-run welcome + Sign in with Apple. Plain-language explanation of what the
/// app does, then auth (Apple is the primary method per the brief).
struct WelcomeView: View {
    let authService: AuthServicing
    let onSignedIn: (Session) -> Void

    @StateObject private var model: AuthViewModel

    init(authService: AuthServicing, onSignedIn: @escaping (Session) -> Void) {
        self.authService = authService
        self.onSignedIn = onSignedIn
        _model = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "shield.lefthalf.filled")
                .font(.system(size: 64))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)

            Text("SafeWord")
                .font(.largeTitle.bold())

            Text("A personal-safety app for your own device. Say the codeword you "
                 + "record, and SafeWord starts a recording of your situation and "
                 + "can alert the people you trust.")
                .font(.body)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal)

            Spacer()

            if let error = model.errorMessage {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("auth.error")
            }

            SignInWithAppleButton(.signIn) { request in
                request.requestedScopes = [.fullName, .email]
            } onCompletion: { result in
                Task { await model.handleAppleCompletion(result, onSignedIn: onSignedIn) }
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 50)
            .padding(.horizontal)
            .disabled(model.isWorking)
            .accessibilityIdentifier("auth.signInWithApple")

            Text("By continuing you'll be asked to confirm how you'll use SafeWord.")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .padding(.bottom)
        }
        .overlay {
            if model.isWorking { ProgressView() }
        }
    }
}
