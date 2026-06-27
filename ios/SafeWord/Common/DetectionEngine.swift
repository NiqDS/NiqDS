import Foundation

/// Wires an `AudioInput` to a `KeywordDetector` and surfaces a single event when
/// the codeword fires. This is the seam M3 builds Armed mode on top of; in M1 it
/// exists so the trigger pipeline is testable end-to-end with mocks (no mic).
///
/// `@MainActor` because consumers (SwiftUI view models) observe `lastResult` and
/// react to triggers on the main actor.
@MainActor
final class DetectionEngine {
    private let input: AudioInput
    private let detector: KeywordDetector

    private(set) var isListening = false
    private(set) var lastResult: DetectionResult = .none
    private var task: Task<Void, Never>?

    /// Called on the main actor when the codeword is detected.
    var onTrigger: ((DetectionResult) -> Void)?

    init(input: AudioInput, detector: KeywordDetector) {
        self.input = input
        self.detector = detector
    }

    func start() throws {
        guard !isListening else { return }
        try input.start()
        isListening = true
        task = Task { [weak self] in
            guard let self else { return }
            for await frame in self.input.frames {
                let result = self.detector.process(frame)
                self.lastResult = result
                if result.detected {
                    self.onTrigger?(result)
                }
            }
        }
    }

    func stop() {
        guard isListening else { return }
        task?.cancel()
        task = nil
        input.stop()
        detector.reset()
        isListening = false
    }
}
