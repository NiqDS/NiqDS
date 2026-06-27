import XCTest
@testable import SafeWord

@MainActor
final class DetectionEngineTests: XCTestCase {
    private func frame(level: Float) -> AudioFrame {
        AudioFrame(samples: [level, level, level], sampleRate: 16_000)
    }

    func testTriggerFiresOnDetectedFrame() async throws {
        let input = MockAudioInput()
        // Treat a "loud" frame as the codeword.
        let detector = MockKeywordDetector { $0.rms > 0.5 }
        let engine = DetectionEngine(input: input, detector: detector)

        let triggered = expectation(description: "codeword fired")
        engine.onTrigger = { result in
            XCTAssertTrue(result.detected)
            triggered.fulfill()
        }

        try engine.start()
        input.emit(frame(level: 0.0)) // silence — no trigger
        input.emit(frame(level: 1.0)) // codeword — should fire

        await fulfillment(of: [triggered], timeout: 1.0)
        XCTAssertTrue(engine.lastResult.detected)
    }

    func testStopFinishesAndResetsDetector() async throws {
        let input = MockAudioInput()
        let detector = MockKeywordDetector { _ in false }
        let engine = DetectionEngine(input: input, detector: detector)

        try engine.start()
        XCTAssertTrue(engine.isListening)
        engine.stop()
        XCTAssertFalse(engine.isListening)
        XCTAssertEqual(detector.resetCount, 1)
        XCTAssertFalse(input.isRunning)
    }

    func testNoRawAudioLeavesEngineWithoutDetection() async throws {
        // Frames flow through the detector but nothing is emitted/triggered when
        // the codeword never fires — the M1 guarantee that listening audio stays
        // on-device until a trigger.
        let input = MockAudioInput()
        let detector = MockKeywordDetector { _ in false }
        let engine = DetectionEngine(input: input, detector: detector)
        engine.onTrigger = { _ in XCTFail("should not trigger") }

        try engine.start()
        for level in stride(from: Float(0), through: 1, by: 0.25) {
            input.emit(frame(level: level))
        }
        input.finish()
        // Give the consumer task a tick to drain.
        try await Task.sleep(nanoseconds: 50_000_000)
        XCTAssertFalse(engine.lastResult.detected)
    }
}
