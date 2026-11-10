// JustVoiceTypeSettings — SwiftUI settings window for Just Voice Type.
// Renders `state` snapshots from Python (stdin, JSON Lines) and reports user
// intents (stdout). See native/settings/PROTOCOL.md.
//
//   JustVoiceTypeSettings                       normal mode (spawned by Python)
//   JustVoiceTypeSettings --demo [state.json]   window on demo-state.json, messages → stderr
//   JustVoiceTypeSettings --render-dir DIR [--state state.json]   PNGs, no window
//   JustVoiceTypeSettings --protocol-selftest   ready → read one state → echo action

import AppKit
import SwiftUI

@main
enum JustVoiceTypeSettingsMain {
    @MainActor
    static func main() {
        let args = Array(CommandLine.arguments.dropFirst())

        if args.contains("--protocol-selftest") {
            exit(ProtocolSelftest.run())
        }
        signal(SIGPIPE, SIG_IGN)
        FontRegistry.registerAll()

        if let i = args.firstIndex(of: "--render-dir") {
            guard i + 1 < args.count else {
                Log.err("--render-dir needs a directory")
                exit(64)
            }
            let statePath = args.firstIndex(of: "--state").flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil }
            _ = NSApplication.shared
            exit(Renderer.run(dir: args[i + 1], statePath: statePath))
        }

        var demoPath: String?
        let demo = args.contains("--demo")
        if let i = args.firstIndex(of: "--demo") {
            if i + 1 < args.count, !args[i + 1].hasPrefix("--") { demoPath = args[i + 1] }
        }

        let app = NSApplication.shared
        let controller = AppController(demo: demo, demoPath: demoPath)
        AppController.shared = controller
        app.delegate = controller
        app.setActivationPolicy(.accessory)
        app.run()
    }
}

enum DemoState {
    static func defaultPath() -> String {
        let fm = FileManager.default
        let cwdPath = "native/settings/demo-state.json"
        if fm.fileExists(atPath: cwdPath) { return cwdPath }
        if let exe = Bundle.main.executableURL?.resolvingSymlinksInPath() {
            let p = exe.deletingLastPathComponent().appendingPathComponent("settings/demo-state.json").path
            if fm.fileExists(atPath: p) { return p }
        }
        return cwdPath
    }

    static func load(_ path: String?) -> StateMessage? {
        let p = path ?? defaultPath()
        do {
            let data = try Data(contentsOf: URL(fileURLWithPath: p))
            return try JSONDecoder().decode(StateMessage.self, from: data)
        } catch {
            Log.err("cannot load state \(p): \(error)")
            return nil
        }
    }
}

@MainActor
final class AppController: NSObject, NSApplicationDelegate, NSWindowDelegate {
    static var shared: AppController?

    let demo: Bool
    let demoPath: String?
    let wire: Wire
    let store: Store
    private var window: NSWindow?
    private var keyMonitor: Any?
    private var closing = false

    init(demo: Bool, demoPath: String?) {
        self.demo = demo
        self.demoPath = demoPath
        self.wire = Wire(demo ? .stderr : .stdout)
        self.store = Store(wire: wire)
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        NSApp.mainMenu = makeMainMenu()
        makeWindow()
        installKeyMonitor()
        NotificationCenter.default.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: nil, queue: .main) { _ in
                MainActor.assumeIsolated {
                    AppController.shared?.store.reduceMotion =
                        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
                }
            }

        if demo {
            if let state = DemoState.load(demoPath) { store.apply(state) }
            wire.send(["type": "ready"])
        } else {
            startReading()
            wire.send(["type": "ready"])
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    // MARK: window

    private func makeWindow() {
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: T.windowSize),
                         styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.titlebarAppearsTransparent = true
        w.titleVisibility = .hidden
        w.title = "Just Voice Type"
        w.appearance = NSAppearance(named: .darkAqua)
        w.backgroundColor = T.nsBg
        w.isReleasedWhenClosed = false
        w.isMovableByWindowBackground = false
        w.delegate = self
        w.standardWindowButton(.zoomButton)?.isEnabled = false

        // Full-size content view: draw under the transparent titlebar too,
        // the traffic lights sit over the sidebar's top padding.
        let root = RootView()
            .environmentObject(store)
            .frame(width: T.windowSize.width, height: T.windowSize.height)
            .ignoresSafeArea()
        let host = NSHostingView(rootView: root)
        host.sizingOptions = []
        host.frame = NSRect(origin: .zero, size: T.windowSize)
        w.contentView = host
        w.setContentSize(T.windowSize)
        w.contentMinSize = T.windowSize
        w.contentMaxSize = T.windowSize
        w.center()

        store.onWindowTitle = { [weak w] title in
            if !title.isEmpty { w?.title = title }
        }
        window = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func bringToFront() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func windowWillClose(_ notification: Notification) {
        finish(sendClosed: true)
    }

    private func finish(sendClosed: Bool) {
        guard !closing else { return }
        closing = true
        if sendClosed { wire.send(["type": "closed"]) }
        exit(0)
    }

    @objc func closeWindow(_ sender: Any?) {
        if let window { window.performClose(sender) } else { finish(sendClosed: true) }
    }

    // MARK: stdin

    private func startReading() {
        let thread = Thread {
            while let line = readLine(strippingNewline: true) {
                if line.trimmingCharacters(in: .whitespaces).isEmpty { continue }
                DispatchQueue.main.async {
                    MainActor.assumeIsolated { AppController.shared?.receive(line) }
                }
            }
            DispatchQueue.main.async {
                // EOF: Python is gone.
                exit(0)
            }
        }
        thread.name = "stdin"
        thread.start()
    }

    func receive(_ line: String) {
        let msg: Inbound
        do {
            msg = try Inbound.parse(line)
        } catch {
            Log.err("bad message: \(error)")
            return
        }
        switch msg {
        case .state(let s): store.apply(s)
        case .focus(let section):
            store.focus(section)
            bringToFront()
        case .toast(let t): store.showToast(t)
        case .quit: finish(sendClosed: false)
        case .unknown(let type): Log.err("unknown message type \(type)")
        }
    }

    // MARK: keyboard

    private func installKeyMonitor() {
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let key: Store.Key?
            switch event.keyCode {
            case 53: key = .escape
            case 126: key = .up
            case 125: key = .down
            case 36, 76: key = .enter
            default: key = nil
            }
            guard let key else { return event }
            let handled = MainActor.assumeIsolated { AppController.shared?.store.handle(key) ?? false }
            return handled ? nil : event
        }
    }

    // MARK: menu (key equivalents for text editing; the menu bar itself is hidden)

    private func makeMainMenu() -> NSMenu {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Close", action: #selector(closeWindow(_:)), keyEquivalent: "w")
        appMenu.addItem(withTitle: "Quit", action: #selector(closeWindow(_:)), keyEquivalent: "q")
        for item in appMenu.items { item.target = self }
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        return main
    }
}
