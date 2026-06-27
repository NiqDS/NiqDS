import Foundation
import Security

/// Secure storage for the session (tokens never touch UserDefaults — Constraint 6).
protocol SecureStore: AnyObject {
    func save(_ data: Data, for key: String) throws
    func read(_ key: String) -> Data?
    func delete(_ key: String) throws
}

enum SecureStoreError: Error {
    case unexpectedStatus(OSStatus)
}

/// Keychain-backed `SecureStore`. Items are `WhenUnlockedThisDeviceOnly` so the
/// session never syncs off-device.
final class KeychainService: SecureStore {
    private let service: String

    init(service: String = "com.example.safeword") {
        self.service = service
    }

    private func baseQuery(_ key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
    }

    func save(_ data: Data, for key: String) throws {
        var query = baseQuery(key)
        SecItemDelete(query as CFDictionary) // replace any existing item
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] =
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw SecureStoreError.unexpectedStatus(status)
        }
    }

    func read(_ key: String) -> Data? {
        var query = baseQuery(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess else { return nil }
        return item as? Data
    }

    func delete(_ key: String) throws {
        let status = SecItemDelete(baseQuery(key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw SecureStoreError.unexpectedStatus(status)
        }
    }
}

/// Stores/loads the `Session` as JSON in a `SecureStore`.
final class SessionStore {
    private static let key = "session.v1"
    private let store: SecureStore

    init(store: SecureStore) {
        self.store = store
    }

    func load() -> Session? {
        guard let data = store.read(Self.key) else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }

    func save(_ session: Session) throws {
        try store.save(JSONEncoder().encode(session), for: Self.key)
    }

    func clear() throws {
        try store.delete(Self.key)
    }
}
