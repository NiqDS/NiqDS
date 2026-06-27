import Foundation

/// Outcome of feeding one frame to the detector.
struct DetectionResult: Equatable {
    let detected: Bool
    let confidence: Float

    static let none = DetectionResult(detected: false, confidence: 0)
}

/// On-device codeword spotter. The production implementation (M2) wraps the
/// chosen engine — **Picovoice Porcupine** (see DECISIONS.md) — fed by rolling
/// `AVAudioEngine` buffers. Detection is on-device only: raw listening audio is
/// never persisted or uploaded (Constraint 4).
///
/// Abstracted behind a protocol so it is mockable in CI and swappable later.
protocol KeywordDetector: AnyObject {
    /// 0.0 (fewer false positives) … 1.0 (fewer missed triggers).
    var sensitivity: Float { get set }

    /// Feed one frame; returns whether the codeword fired this frame.
    func process(_ frame: AudioFrame) -> DetectionResult

    /// Forget any rolling-buffer state (e.g. when disarming).
    func reset()
}
