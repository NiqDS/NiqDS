import Foundation
@testable import SafeWord

// MARK: - Audio / detection mocks (so CI needs no microphone)

/// Test double for `AudioInput`. Frames are pushed manually via `emit`.
final class MockAudioInput: AudioInput {
    let frames: AsyncStream<AudioFrame>
    private let continuation: AsyncStream<AudioFrame>.Continuation
    private(set) var isRunning = false

    init() {
        var captured: AsyncStream<AudioFrame>.Continuation!
        frames = AsyncStream { captured = $0 }
        continuation = captured
    }

    func start() throws { isRunning = true }
    func stop() {
        isRunning = false
        continuation.finish()
    }

    func emit(_ frame: AudioFrame) { continuation.yield(frame) }
    func finish() { continuation.finish() }
}

/// Test double for `KeywordDetector`; detection is driven by an injected closure.
final class MockKeywordDetector: KeywordDetector {
    var sensitivity: Float = 0.5
    private(set) var resetCount = 0
    private let shouldDetect: (AudioFrame) -> Bool

    init(shouldDetect: @escaping (AudioFrame) -> Bool) {
        self.shouldDetect = shouldDetect
    }

    func process(_ frame: AudioFrame) -> DetectionResult {
        shouldDetect(frame)
            ? DetectionResult(detected: true, confidence: 0.99)
            : .none
    }

    func reset() { resetCount += 1 }
}

// MARK: - Storage mocks

final class InMemorySecureStore: SecureStore {
    private var storage: [String: Data] = [:]
    func save(_ data: Data, for key: String) throws { storage[key] = data }
    func read(_ key: String) -> Data? { storage[key] }
    func delete(_ key: String) throws { storage[key] = nil }
}

final class InMemoryConsentStore: ConsentStoring {
    private var record: ConsentRecord?
    func currentRecord() -> ConsentRecord? { record }
    func save(_ record: ConsentRecord) throws { self.record = record }
    func clear() { record = nil }
}

// MARK: - Auth mocks

final class FakeAuthService: AuthServicing {
    var restored: Session?
    var signInResult: Session?
    private(set) var recordedConsents: [ConsentRecord] = []
    private(set) var deleteCount = 0
    private(set) var signOutCount = 0

    func restoreSession() -> Session? { restored }

    func signInWithApple(identityToken: String, displayName: String?) async throws -> Session {
        guard let signInResult else {
            throw APIError(status: 500, code: "no_stub", message: "no stub")
        }
        restored = signInResult
        return signInResult
    }

    func recordConsent(_ record: ConsentRecord, session: Session) async throws {
        recordedConsents.append(record)
    }

    func deleteAccount(session: Session) async throws {
        deleteCount += 1
        restored = nil
    }

    func signOut() {
        signOutCount += 1
        restored = nil
    }
}

/// Canned `APIClienting` keyed by request path; records what was sent.
final class MockAPIClient: APIClienting, @unchecked Sendable {
    var jsonByPath: [String: Data] = [:]
    private(set) var sentRequests: [(path: String, bearer: String?)] = []

    func send<Response: Decodable>(
        _ request: APIRequest,
        bearer: String?,
        as _: Response.Type
    ) async throws -> Response {
        sentRequests.append((request.path, bearer))
        guard let data = jsonByPath[request.path] else {
            throw APIError(status: 404, code: "no_stub", message: "no stub for \(request.path)")
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }

    func sendNoContent(_ request: APIRequest, bearer: String?) async throws {
        sentRequests.append((request.path, bearer))
    }
}

// MARK: - Fixtures

enum Fixtures {
    static func session() -> Session {
        Session(
            user: UserProfile(id: "u1", email: "a@b.com", displayName: "Tester"),
            tokens: TokenPair(accessToken: "access", refreshToken: "refresh")
        )
    }

    static func fullConsent() -> ConsentRecord {
        ConsentRecord.make(affirmed: Set(ConsentClause.allCases))
    }
}
