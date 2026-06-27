import SwiftUI

/// The consent gate (Constraint 2). The "Continue" action is disabled until every
/// clause is affirmed, so the app cannot be entered without explicit, logged
/// consent. This is the structural enforcement of the non-covert design.
struct ConsentView: View {
    let onAccept: (ConsentRecord) -> Void

    @StateObject private var model = ConsentViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("SafeWord is a consent-based safety tool — not a way to "
                         + "secretly record other people. Please confirm:")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                Section {
                    ForEach(ConsentClause.allCases) { clause in
                        Toggle(isOn: model.binding(for: clause)) {
                            Text(clause.statement)
                                .font(.callout)
                        }
                        .accessibilityIdentifier("consent.toggle.\(clause.rawValue)")
                    }
                }

                Section {
                    Button {
                        if let record = model.makeRecord() { onAccept(record) }
                    } label: {
                        Text("I Agree & Continue")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.allAffirmed)
                    .accessibilityIdentifier("consent.continue")
                } footer: {
                    Text("Consent version \(ConsentVersion.current). We store the time "
                         + "you agreed and which statements you confirmed.")
                }
            }
            .navigationTitle("Before you start")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
