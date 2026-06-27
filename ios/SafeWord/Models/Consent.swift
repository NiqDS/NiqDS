import Foundation

/// The clauses a user must affirm at onboarding (Constraint 2). Each maps to a
/// checkbox in the consent gate; all must be `true` to proceed.
enum ConsentClause: String, CaseIterable, Identifiable, Codable {
    case lawfulUse
    case partyToConversation
    case deviceOwnership

    var id: String { rawValue }

    var statement: String {
        switch self {
        case .lawfulUse:
            return "I am responsible for complying with the recording and consent "
                + "laws that apply where I am."
        case .partyToConversation:
            return "I will only use SafeWord to record situations I am personally "
                + "part of — not to secretly record other people."
        case .deviceOwnership:
            return "I own, or am authorised to use, the device SafeWord is "
                + "installed on."
        }
    }
}

/// Bumping this re-gates every user through consent on next launch.
enum ConsentVersion {
    static let current = "1.0.0"
}

/// A persisted consent record. Stored locally and mirrored to the backend.
struct ConsentRecord: Codable, Equatable {
    let version: String
    let acknowledged: [String: Bool]
    let acceptedAt: Date

    /// Valid only if it matches the current version AND every clause is affirmed.
    var satisfiesCurrentVersion: Bool {
        guard version == ConsentVersion.current else { return false }
        return ConsentClause.allCases.allSatisfy { acknowledged[$0.rawValue] == true }
    }

    static func make(affirmed: Set<ConsentClause>, at date: Date = .init()) -> ConsentRecord {
        var ack: [String: Bool] = [:]
        for clause in ConsentClause.allCases {
            ack[clause.rawValue] = affirmed.contains(clause)
        }
        return ConsentRecord(
            version: ConsentVersion.current,
            acknowledged: ack,
            acceptedAt: date
        )
    }
}
