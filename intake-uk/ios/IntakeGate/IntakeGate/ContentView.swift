import SwiftUI

struct ContentView: View {
    // The Intake Gate server. Set to your Mac's LAN address while developing
    // (e.g. http://192.168.0.10:8000) or your deployed https URL. Editable in-app.
    @AppStorage("serverURL") private var serverURL: String = "http://127.0.0.1:8000"
    @State private var showSettings = false
    @State private var reloadToken = 0

    var body: some View {
        NavigationStack {
            WebContainer(urlString: serverURL, reloadToken: reloadToken)
                .ignoresSafeArea(edges: .bottom)
                .navigationTitle("Intake Gate")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { reloadToken += 1 } label: {
                            Image(systemName: "arrow.clockwise")
                        }
                        .accessibilityLabel("Reload")
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { showSettings = true } label: {
                            Image(systemName: "gearshape")
                        }
                        .accessibilityLabel("Settings")
                    }
                }
                .sheet(isPresented: $showSettings) {
                    SettingsView(serverURL: $serverURL) { reloadToken += 1 }
                }
        }
    }
}

struct SettingsView: View {
    @Binding var serverURL: String
    var onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draft: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Server address") {
                    TextField("http://192.168.0.10:8000", text: $draft)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                    Text("Point this at your Intake Gate server — your Mac's LAN address "
                         + "while developing, or your deployed https URL.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        serverURL = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                        onSave()
                        dismiss()
                    }
                }
            }
            .onAppear { draft = serverURL }
        }
    }
}

#Preview {
    ContentView()
}
