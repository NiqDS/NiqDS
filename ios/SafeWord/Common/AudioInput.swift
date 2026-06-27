import Foundation

/// A buffer of mono PCM samples handed to the detection layer.
struct AudioFrame: Equatable {
    let samples: [Float]
    let sampleRate: Double

    /// Simple RMS energy — used for level metering and silence gating.
    var rms: Float {
        guard !samples.isEmpty else { return 0 }
        let sumSq = samples.reduce(Float(0)) { $0 + $1 * $1 }
        return (sumSq / Float(samples.count)).squareRoot()
    }
}

/// Source of microphone frames. The production implementation (M2/M3) wraps
/// `AVAudioEngine`; tests use `MockAudioInput`, so CI never needs real hardware
/// (per the brief's "mockable detection layer" requirement).
protocol AudioInput: AnyObject {
    /// Frames emitted while running. Finishes when `stop()` is called.
    var frames: AsyncStream<AudioFrame> { get }
    var isRunning: Bool { get }

    func start() throws
    func stop()
}
