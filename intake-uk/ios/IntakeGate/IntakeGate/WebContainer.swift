import SwiftUI
import WebKit

/// Hosts a WKWebView that renders the Intake Gate web app. On iOS, WKWebView
/// presents the camera / photo picker natively for `<input type="file"
/// capture>` — so "Take a photo" in the web app opens the camera here, provided
/// the camera / photo-library usage strings are present in Info.plist.
struct WebContainer: UIViewRepresentable {
    let urlString: String
    let reloadToken: Int

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        context.coordinator.webView = webView
        load(webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastToken != reloadToken
            || context.coordinator.lastURL != urlString {
            context.coordinator.lastToken = reloadToken
            context.coordinator.lastURL = urlString
            load(webView)
        }
    }

    private func load(_ webView: WKWebView) {
        guard let url = URL(string: urlString) else { return }
        webView.load(URLRequest(url: url))
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var webView: WKWebView?
        var lastToken = -1
        var lastURL = ""
    }
}
