// --offer: a small panel «Google Chrome is using the microphone — Record?».
//
// Python (voice_type.py → offer_prompt.py) starts the helper with --offer and
// writes one JSON line with the ready-made strings:
//   {"type":"offer","title":…,"body":…,"record":…,"dismiss":…,"hint":…,"key":…,"ignore":…}
// The panel answers with one line and exits:
//   {"type":"offer_answer","answer":"record"|"dismiss"|"ignore"}
// "ignore" — «Don't offer for {app}»: Python adds the app to the ignore list.
// No "ignore" string (an app without a bundle id) — no such button.
// Python withdraws the panel by closing stdin (the call app left the
// microphone): EOF → exit without an answer.
//
// The panel never activates the app and never takes focus away from the call:
// a non-activating panel that still accepts the first click.

import AppKit
import SwiftUI

struct OfferModel: Decodable, Equatable {
    let title: String
    let body: String
    let record: String
    let dismiss: String
    let hint: String?
    let key: String?
    let ignore: String?

    static let demo = OfferModel(
        title: "Google Chrome использует микрофон",
        body: "Записать звонок? Запись остановится сама, когда звонок закончится.",
        record: "Записать",
        dismiss: "Не сейчас",
        hint: "или",
        key: "F13",
        ignore: "Не предлагать для Google Chrome")
}

enum OfferLayout {
    static let width: CGFloat = 372
    static let margin: CGFloat = 12
}

struct OfferView: View {
    let model: OfferModel
    let answer: (String) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "phone")
                .font(F.icon(13))
                .foregroundColor(T.ink)
                .frame(width: 28, height: 28)
                .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
            VStack(alignment: .leading, spacing: 0) {
                Text(model.title)
                    .type(.ui, 13.5, 600, lh: 1.3)
                    .foregroundColor(T.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Text(model.body)
                    .type(.ui, 12.5, 400, lh: 1.4)
                    .foregroundColor(T.ink2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 2)
                HStack(spacing: 8) {
                    ConsoleButton(title: model.record, kind: .primary) { answer("record") }
                    ConsoleButton(title: model.dismiss) { answer("dismiss") }
                    Spacer(minLength: 8)
                    if let key = model.key, !key.isEmpty {
                        HStack(spacing: 6) {
                            if let hint = model.hint, !hint.isEmpty {
                                Text(hint).font(F.ui(12)).foregroundColor(T.ink3)
                            }
                            KeyCap(text: key).foregroundColor(T.ink2)
                        }
                    }
                }
                .padding(.top, 12)
                if let ignore = model.ignore, !ignore.isEmpty {
                    QuietButton(title: ignore) { answer("ignore") }
                        .padding(.top, 10)
                }
            }
        }
        .padding(14)
        .frame(width: OfferLayout.width, alignment: .leading)
        .background(T.raise)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
        .clipShape(RoundedRectangle(cornerRadius: T.radius))
        .environment(\.colorScheme, .dark)
    }
}

/// A secondary action that should not compete with Record / Not now.
private struct QuietButton: View {
    let title: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .underline(hover)
                .font(F.ui(12))
                .foregroundColor(hover ? T.ink2 : T.ink3)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .fixedSize()
    }
}

/// Borderless panels refuse key status by default; this one takes it (without
/// activating the app) so its buttons get keyboard and mouse events.
final class OfferWindow: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

/// Lets the first click on a non-key panel press the button instead of only
/// focusing the window.
final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

@MainActor
enum OfferMode {
    static func run() -> Never {
        guard let line = readLine(strippingNewline: true),
              let data = line.data(using: .utf8),
              let model = try? JSONDecoder().decode(OfferModel.self, from: data)
        else {
            Log.err("--offer: expected one JSON line on stdin")
            exit(65)
        }
        let app = NSApplication.shared
        let controller = OfferController(model: model)
        OfferController.shared = controller
        app.delegate = controller
        app.setActivationPolicy(.accessory)
        app.run()
        exit(0)
    }
}

@MainActor
final class OfferController: NSObject, NSApplicationDelegate {
    static var shared: OfferController?

    let model: OfferModel
    private var panel: OfferWindow?
    private var answered = false

    init(model: OfferModel) {
        self.model = model
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        show()
        watchStdin()
    }

    private func show() {
        let view = OfferView(model: model) { [weak self] answer in
            MainActor.assumeIsolated { self?.finish(answer) }
        }
        let host = FirstMouseHostingView(rootView: view)
        let size = host.fittingSize
        let p = OfferWindow(contentRect: NSRect(origin: .zero, size: size),
                            styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        p.contentView = host
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.isFloatingPanel = true  // sets .floating level — override right after
        p.level = .statusBar      // above full-screen apps, like a notification
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.hidesOnDeactivate = false
        p.becomesKeyOnlyIfNeeded = true
        p.isReleasedWhenClosed = false
        // not in screen shares / recordings where macOS honours it: the
        // prompt is for you, not for the people on the call
        p.sharingType = .none

        let screen = NSScreen.main ?? NSScreen.screens.first
        if let vf = screen?.visibleFrame {
            p.setFrameOrigin(NSPoint(x: vf.maxX - size.width - OfferLayout.margin,
                                     y: vf.maxY - size.height - OfferLayout.margin))
        }
        let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        p.alphaValue = 0
        p.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = reduce ? 0.1 : 0.18
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.22, 1, 0.36, 1)
            p.animator().alphaValue = 1
        }
        panel = p
    }

    /// EOF on stdin: Python withdrew the offer (the call app left the mic).
    private func watchStdin() {
        let thread = Thread {
            while readLine(strippingNewline: true) != nil {}
            DispatchQueue.main.async { exit(0) }
        }
        thread.name = "stdin"
        thread.start()
    }

    func finish(_ answer: String) {
        guard !answered else { return }
        answered = true
        let msg = ["type": "offer_answer", "answer": answer]
        if let data = try? JSONSerialization.data(withJSONObject: msg),
           let text = String(data: data, encoding: .utf8) {
            print(text)
            fflush(stdout)
        }
        panel?.orderOut(nil)
        exit(0)
    }
}
