import SwiftUI

/// M1 placeholder for the main experience. The Arm toggle and triggered recording
/// arrive in M2/M3; for now this confirms the signed-in + consented state and
/// hosts account management (sign out, and the App Store-required account
/// deletion).
struct ArmedHomeView: View {
    let session: Session
    let onSignOut: () -> Void
    let onDeleteAccount: () -> Void

    @State private var showDeleteConfirmation = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Not armed", systemImage: "shield.slash")
                            .font(.headline)
                        Text("Codeword enrollment and Armed mode arrive in the next "
                             + "milestone. When armed, SafeWord will always show a "
                             + "visible recording indicator — it never records "
                             + "secretly.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)

                    Button {
                        // Enabled in M3.
                    } label: {
                        Label("Arm SafeWord", systemImage: "shield.lefthalf.filled")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(true)
                }

                Section("Account") {
                    if let name = session.user.displayName {
                        LabeledContent("Name", value: name)
                    }
                    if let email = session.user.email {
                        LabeledContent("Email", value: email)
                    }
                    Button("Sign Out", action: onSignOut)
                    Button("Delete Account", role: .destructive) {
                        showDeleteConfirmation = true
                    }
                    .accessibilityIdentifier("account.delete")
                }
            }
            .navigationTitle("SafeWord")
            .confirmationDialog(
                "Delete your account?",
                isPresented: $showDeleteConfirmation,
                titleVisibility: .visible
            ) {
                Button("Delete Everything", role: .destructive, action: onDeleteAccount)
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This permanently deletes your account and all SafeWord data "
                     + "from our servers. This cannot be undone.")
            }
        }
    }
}
