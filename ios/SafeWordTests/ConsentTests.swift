import XCTest
@testable import SafeWord

final class ConsentTests: XCTestCase {
    func testFullConsentSatisfiesCurrentVersion() {
        let record = ConsentRecord.make(affirmed: Set(ConsentClause.allCases))
        XCTAssertTrue(record.satisfiesCurrentVersion)
    }

    func testPartialConsentIsNotSatisfied() {
        let record = ConsentRecord.make(affirmed: [.lawfulUse])
        XCTAssertFalse(record.satisfiesCurrentVersion)
    }

    func testOldVersionRecordIsNotSatisfied() {
        // Simulate a record from a previous consent version.
        let stale = ConsentRecord(
            version: "0.9.0",
            acknowledged: Dictionary(
                uniqueKeysWithValues: ConsentClause.allCases.map { ($0.rawValue, true) }
            ),
            acceptedAt: Date()
        )
        XCTAssertFalse(stale.satisfiesCurrentVersion)
    }

    @MainActor
    func testViewModelGatesUntilAllAffirmed() {
        let model = ConsentViewModel()
        XCTAssertFalse(model.allAffirmed)
        XCTAssertNil(model.makeRecord())

        for clause in ConsentClause.allCases {
            model.binding(for: clause).wrappedValue = true
        }
        XCTAssertTrue(model.allAffirmed)
        let record = model.makeRecord()
        XCTAssertNotNil(record)
        XCTAssertTrue(record?.satisfiesCurrentVersion ?? false)
    }

    @MainActor
    func testToggleOffRemovesAffirmation() {
        let model = ConsentViewModel()
        model.binding(for: .lawfulUse).wrappedValue = true
        XCTAssertTrue(model.binding(for: .lawfulUse).wrappedValue)
        model.binding(for: .lawfulUse).wrappedValue = false
        XCTAssertFalse(model.binding(for: .lawfulUse).wrappedValue)
    }
}
