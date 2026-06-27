import SwiftUI

/// Tracks which consent clauses are affirmed and builds the resulting record.
/// Kept separate from the view so the gating logic is unit-testable.
@MainActor
final class ConsentViewModel: ObservableObject {
    @Published private(set) var affirmed: Set<ConsentClause> = []

    var allAffirmed: Bool {
        ConsentClause.allCases.allSatisfy { affirmed.contains($0) }
    }

    func binding(for clause: ConsentClause) -> Binding<Bool> {
        Binding(
            get: { self.affirmed.contains(clause) },
            set: { isOn in
                if isOn { self.affirmed.insert(clause) }
                else { self.affirmed.remove(clause) }
            }
        )
    }

    /// Returns a record only when every clause is affirmed; otherwise nil so the
    /// caller can't accidentally proceed with partial consent.
    func makeRecord(now: Date = .init()) -> ConsentRecord? {
        guard allAffirmed else { return nil }
        return ConsentRecord.make(affirmed: affirmed, at: now)
    }
}
