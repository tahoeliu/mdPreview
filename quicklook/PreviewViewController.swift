import Cocoa
import Quartz
import WebKit

/// Finder 空格预览：加载与主应用相同的渲染管线（marked + DOMPurify + KaTeX），不联网、不执行文档里的脚本。
@objc(PreviewViewController)
final class PreviewViewController: NSViewController, QLPreviewingController, WKNavigationDelegate {
    private static let maximumBytes = 2 * 1024 * 1024
    private var webView: WKWebView!
    private var job: (text: String, started: Date, handler: (Error?) -> Void)?

    override func loadView() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 720, height: 900), configuration: configuration)
        webView.navigationDelegate = self
        view = webView
    }

    func preparePreviewOfFile(at url: URL, completionHandler handler: @escaping (Error?) -> Void) {
        do {
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            let data = try handle.read(upToCount: Self.maximumBytes) ?? Data()
            var converted: NSString?
            var lossy = ObjCBool(false)
            _ = NSString.stringEncoding(for: data, encodingOptions: nil, convertedString: &converted, usedLossyConversion: &lossy)
            var text = (converted as String?) ?? String(decoding: data, as: UTF8.self)
            if text.hasPrefix("\u{FEFF}") { text.removeFirst() }
            guard let page = Bundle(for: PreviewViewController.self).url(forResource: "preview", withExtension: "html", subdirectory: "web") else {
                throw CocoaError(.fileNoSuchFile)
            }
            job = (text, Date(), handler)
            webView.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
        } catch {
            handler(error)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let current = job else { return }
        job = nil
        guard let payload = try? JSONSerialization.data(withJSONObject: [current.text]),
              let json = String(data: payload, encoding: .utf8) else {
            current.handler(CocoaError(.coderInvalidValue))
            return
        }
        webView.evaluateJavaScript("window.renderMarkdownPreview(\(json)[0])") { [weak self] result, error in
            self?.recordDiagnostics(result: result, error: error, started: current.started)
            current.handler(error)
        }
    }

    /// 只在本扩展自己的沙盒容器里写一条无正文、无路径的诊断，便于验收“确实渲染成功”。
    private func recordDiagnostics(result: Any?, error: Error?, started: Date) {
        var report: [String: Any] = ["ok": error == nil, "ms": Int(Date().timeIntervalSince(started) * 1000)]
        if let values = result as? [String: Any] {
            for key in ["elements", "headings", "formulas", "blocked_images"] { report[key] = values[key] }
        }
        guard let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first,
              let data = try? JSONSerialization.data(withJSONObject: report) else { return }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? data.write(to: directory.appendingPathComponent("last-preview.json"))
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // 只允许加载预览页本身；文档里的任何链接都不跳转。
        decisionHandler(navigationAction.navigationType == .other ? .allow : .cancel)
    }
}
