import XCTest
@testable import SafeWord

@MainActor
final class AppViewModelTests: XCTestCase {
    private func makeModel(
        auth: FakeAuthService,
        consent: InMemoryConsentStore
    ) -> AppViewModel {
        let env = AppEnvironment(authService: auth, consentStore: consent)
        return AppViewModel(environment: env)
    }

    func testBootstrapSignedOutWhenNoSession() {
        let model = makeModel(auth: FakeAuthService(), consent: InMemoryConsentStore())
        model.bootstrap()
        XCTAssertEqual(model.flow, .signedOut)
    }

    func testBootstrapNeedsConsentWhenSessionButNoConsent() {
        let auth = FakeAuthService()
        auth.restored = Fixtures.session()
        let model = makeModel(auth: auth, consent: InMemoryConsentStore())
        model.bootstrap()
        guard case .needsConsent = model.flow else {
            return XCTFail("expected needsConsent, got \(model.flow)")
        }
    }

    func testBootstrapReadyWhenSessionAndConsent() throws {
        let auth = FakeAuthService()
        auth.restored = Fixtures.session()
        let consent = InMemoryConsentStore()
        try consent.save(Fixtures.fullConsent())
        let model = makeModel(auth: auth, consent: consent)
        model.bootstrap()
        guard case .ready = model.flow else {
            return XCTFail("expected ready, got \(model.flow)")
        }
    }

    func testSignInRoutesToConsentThenReady() async throws {
        let auth = FakeAuthService()
        let consent = InMemoryConsentStore()
        let model = makeModel(auth: auth, consent: consent)

        let session = Fixtures.session()
        model.didSignIn(session)
        guard case .needsConsent = model.flow else {
            return XCTFail("expected needsConsent after sign-in")
        }

        await model.didAcceptConsent(Fixtures.fullConsent(), for: session)
        guard case .ready = model.flow else {
            return XCTFail("expected ready after consent")
        }
        // Consent was persisted locally and mirrored to the backend.
        XCTAssertTrue(consent.hasValidConsent())
        XCTAssertEqual(auth.recordedConsents.count, 1)
    }

    func testDeleteAccountReturnsToSignedOutAndClearsConsent() async throws {
        let auth = FakeAuthService()
        auth.restored = Fixtures.session()
        let consent = InMemoryConsentStore()
        try consent.save(Fixtures.fullConsent())
        let model = makeModel(auth: auth, consent: consent)

        await model.deleteAccount(Fixtures.session())
        XCTAssertEqual(model.flow, .signedOut)
        XCTAssertEqual(auth.deleteCount, 1)
        XCTAssertFalse(consent.hasValidConsent())
    }

    func testSignOutReturnsToSignedOut() {
        let auth = FakeAuthService()
        auth.restored = Fixtures.session()
        let model = makeModel(auth: auth, consent: InMemoryConsentStore())
        model.signOut()
        XCTAssertEqual(model.flow, .signedOut)
        XCTAssertEqual(auth.signOutCount, 1)
    }
}
