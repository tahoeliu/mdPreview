// 验收用的最小宿主：用 QLPreviewView 走与 Finder 相同的系统预览通道（会经过 Quick Look 扩展）。
// 用法：preview-host <文件> [存活秒数]
import Cocoa
import Quartz

final class Host: NSObject, NSApplicationDelegate {
    let url: URL
    let seconds: Double
    var window: NSWindow!
    init(url: URL, seconds: Double) { self.url = url; self.seconds = seconds }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let frame = NSRect(x: 80, y: 80, width: 820, height: 700)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable], backing: .buffered, defer: false)
        let preview = QLPreviewView(frame: NSRect(origin: .zero, size: frame.size), style: .normal)!
        preview.previewItem = url as NSURL
        window.contentView = preview
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { NSApp.terminate(nil) }
    }
}

let arguments = CommandLine.arguments
guard arguments.count >= 2 else { FileHandle.standardError.write(Data("usage: preview-host file [seconds]\n".utf8)); exit(2) }
let application = NSApplication.shared
application.setActivationPolicy(.regular)
let host = Host(url: URL(fileURLWithPath: arguments[1]), seconds: arguments.count > 2 ? Double(arguments[2]) ?? 20 : 20)
application.delegate = host
application.run()
