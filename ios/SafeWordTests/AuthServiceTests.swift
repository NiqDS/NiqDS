import XCTest
@testable import SafeWord

final class AuthServiceTests: XCTestCase {
    func testSignInPersistsSessionAndReturnsProfile() async throws {
        let api = MockAPIClient()
        api.jsonByPath["v1/auth/apple"] = Data("""
        {
          "user": { "id": "u1", "email": "a@b.com", "displayName": "Tester" },
          "accessToken": "acc",
          "refreshToken": "ref"
        }
        """.utf8)

        let secureStore = InMemorySecureStore()
        let service = AuthService(api: api, sessionStore: SessionStore(store: secureStore))

        let session = try await service.signInWithApple(
            identityToken: "apple-token",
            displayName: "Tester"
        )

        XCTAssertEqual(session.user.id, "u1")
        XCTAssertEqual(session.tokens.accessToken, "acc")
        // Sign-in hit the right endpoint with no bearer.
        XCTAssertEqual(api.sentRequests.first?.path, "v1/auth/apple")
        XCTAssertNil(api.sentRequests.first?.bearer)
        // Session was persisted and is restorable.
        XCTAssertEqual(service.restoreSession()?.user.id, "u1")
    }

    func testRecordConsentSendsBearer() async throws {
        let api = MockAPIClient()
        let service = AuthService(api: api, sessionStore: SessionStore(store: InMemorySecureStore()))
        let session = Fixtures.session()

        try await service.recordConsent(Fixtures.fullConsent(), session: session)

        XCTAssertEqual(api.sentRequests.last?.path, "v1/me/consent")
        XCTAssertEqual(api.sentRequests.last?.bearer, session.tokens.accessToken)
    }

    func testSignOutClearsPersistedSession() async throws {
        let api = MockAPIClient()
        api.jsonByPath["v1/auth/apple"] = Data("""
        { "user": { "id": "u1", "email": null, "displayName": null },
          "accessToken": "acc", "refreshToken": "ref" }
        """.utf8)
        let service = AuthService(api: api, sessionStore: SessionStore(store: InMemorySecureStore()))

        _ = try await service.signInWithApple(identityToken: "t", displayName: nil)
        XCTAssertNotNil(service.restoreSession())
        service.signOut()
        XCTAssertNil(service.restoreSession())
    }
}
