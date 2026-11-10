// --render-dir DIR [--state path]: render every section to PNG at 2× with
// ImageRenderer (no window), for visual checks against the mockup.

import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
enum Renderer {
    struct Variant {
        let name: String
        var section: Section
        var callsExpanded = false
        var sheet = false
        var menu: String? = nil
        var editTerm: Int? = nil
        var addTerm: String? = nil
        var vocabAdd = false
        var full = false
    }

    static let variants: [Variant] = {
        var v: [Variant] = [
            Variant(name: "general", section: .general),
            Variant(name: "recognition", section: .recognition),
            Variant(name: "calls", section: .calls),
            Variant(name: "calls-expanded", section: .calls, callsExpanded: true),
            Variant(name: "terms", section: .terms),
            Variant(name: "about", section: .about),
            Variant(name: "recognition-sheet", section: .recognition, sheet: true),
            Variant(name: "general-menu", section: .general, menu: "hotkey"),
            Variant(name: "terms-edit", section: .terms, editTerm: 1),
            Variant(name: "terms-add", section: .terms, addTerm: ""),
        ]
        for base in ["general", "recognition", "calls", "calls-expanded", "terms", "about"] {
            if var f = v.first(where: { $0.name == base }) {
                f = Variant(name: base + "-full", section: f.section, callsExpanded: f.callsExpanded, full: true)
                v.append(f)
            }
        }
        var vocab = Variant(name: "recognition-vocab-add", section: .recognition, full: true)
        vocab.vocabAdd = true
        v.append(vocab)
        return v
    }()

    static func run(dir: String, statePath: String?) -> Int32 {
        guard let state = DemoState.load(statePath) else { return 2 }
        let out = URL(fileURLWithPath: dir, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        } catch {
            Log.err("cannot create \(dir): \(error)")
            return 1
        }
        var failed = false
        for v in variants {
            let store = Store(wire: Wire(.stderr))
            store.apply(state)
            store.section = v.section
            store.callsExpanded = v.callsExpanded
            store.sheetOpen = v.sheet
            if let m = v.menu, let picker = picker(state, m) {
                store.openMenu(id: m, picker: picker, current: picker.value)
            }
            if let i = v.editTerm { store.startEdit(i) }
            if let h = v.addTerm {
                store.startAdd(heard: h)
                if let err = state.errors["term"] { store.termEditor?.error = err }
            }
            if v.vocabAdd { store.vocabEditor = VocabEditor() }

            let mode: SnapshotMode = v.full ? .full : .window
            let content = RootView()
                .environmentObject(store)
                .environment(\.snapshotMode, mode)
                .environment(\.colorScheme, .dark)
            let view: AnyView
            if v.full {
                view = AnyView(content
                    .frame(width: T.windowSize.width)
                    .frame(minHeight: T.windowSize.height, alignment: .top)
                    .fixedSize(horizontal: false, vertical: true)
                    .background(T.bg))
            } else {
                view = AnyView(content
                    .frame(width: T.windowSize.width, height: T.windowSize.height)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .overlay { RoundedRectangle(cornerRadius: 6).strokeBorder(T.lineStrong, lineWidth: 1) }
                    .background(Color.black))
            }
            let renderer = ImageRenderer(content: view)
            renderer.scale = 2
            guard let cg = renderer.cgImage else {
                Log.err("render failed: \(v.name)")
                failed = true
                continue
            }
            let url = out.appendingPathComponent(v.name + ".png")
            if write(cg, to: url) {
                print(url.path)
            } else {
                failed = true
            }
        }
        return failed ? 1 : 0
    }

    private static func picker(_ s: StateMessage, _ key: String) -> PickerModel? {
        switch key {
        case "hotkey": return s.data.general.hotkey
        case "insert_mode": return s.data.general.insertMode
        case "ui_language": return s.data.general.uiLanguage
        case "call_hotkey": return s.data.calls.callHotkey
        case "call_device": return s.data.calls.device
        default: return nil
        }
    }

    private static func write(_ image: CGImage, to url: URL) -> Bool {
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
        else { return false }
        CGImageDestinationAddImage(dest, image, nil)
        return CGImageDestinationFinalize(dest)
    }
}
