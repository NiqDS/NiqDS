import Foundation

/// Persists the local consent record and answers the gate question: has this user
/// affirmed the *current* consent version? (Constraint 2 / structurally enforced.)
protocol ConsentStoring: AnyObject {
    func currentRecord() -> ConsentRecord?
    func save(_ record: ConsentRecord) throws
    func clear()

    /// True only when a record exists, matches `ConsentVersion.current`, and has
    /// every clause affirmed.
    func hasValidConsent() -> Bool
}

extension ConsentStoring {
    func hasValidConsent() -> Bool {
        currentRecord()?.satisfiesCurrentVersion ?? false
    }
}

/// `UserDefaults`-backed store. Consent metadata is not a secret, so this is the
/// right home (tokens go to the Keychain instead).
final class ConsentStore: ConsentStoring {
    private static let key = "consent.record.v1"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func currentRecord() -> ConsentRecord? {
        guard let data = defaults.data(forKey: Self.key) else { return nil }
        return try? JSONDecoder().decode(ConsentRecord.self, from: data)
    }

    func save(_ record: ConsentRecord) throws {
        let data = try JSONEncoder().encode(record)
        defaults.set(data, forKey: Self.key)
    }

    func clear() {
        defaults.removeObject(forKey: Self.key)
    }
}
