// The latest snapshot from Python plus UI-local state (current section, open
// editors, search text, open menu, toast). No business logic lives here:
// every change is reported to Python and the next snapshot wins.

import AppKit
import SwiftUI

enum Section: String, CaseIterable, Identifiable {
    case general, recognition, calls, terms, about
    var id: String { rawValue }
}

struct TermEditor: Equatable {
    enum Mode: Equatable { case add, edit(Int) }
    var mode: Mode
    var heard: String
    var wanted: String
    var originalHeard = ""
    var originalWanted = ""
    var pendingReq: String?
    var error: String?
}

struct VocabEditor: Equatable {
    var text = ""
    var pendingReq: String?
    var error: String?
}

struct OpenMenu: Equatable {
    let id: String           // the `set` key of the picker
    let options: [PickerOption]
    let current: String?
    var highlight: Int?
}

struct ToastState: Equatable, Identifiable {
    let id = UUID()
    let text: String
    let action: ToastAction?
}

@MainActor
final class Store: ObservableObject {
    @Published private(set) var snap: StateMessage?
    @Published var section: Section = .general
    @Published var callsExpanded = false
    @Published var callQuery = ""
    @Published var termQuery = ""
    @Published var termEditor: TermEditor?
    @Published var vocabEditor: VocabEditor?
    @Published var sheetOpen = false
    @Published var sheetQuery = ""
    @Published var menu: OpenMenu?
    @Published var toast: ToastState?
    @Published var copiedCall: String?
    /// Optimistic values per `set` key; cleared by every snapshot.
    @Published private(set) var optimistic: [String: JSONValue] = [:]

    var reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    var onWindowTitle: ((String) -> Void)?

    private let wire: Wire
    private var reqSeq = 0

    init(wire: Wire) {
        self.wire = wire
    }

    // MARK: strings

    func s(_ key: String) -> String { snap?.strings[key] ?? key }
    func s(_ key: String, n: Int) -> String { s(key).replacingOccurrences(of: "{n}", with: String(n)) }
    func s(_ key: String, q: String) -> String { s(key).replacingOccurrences(of: "{q}", with: q) }
    func has(_ key: String) -> Bool { snap?.strings[key] != nil }
    func error(_ key: String) -> String? { snap?.errors[key] }

    // MARK: values (snapshot + optimistic overlay)

    func pickerValue(_ key: String, _ picker: PickerModel) -> String? {
        if let v = optimistic[key] { return v.string }
        return picker.value
    }

    func toggleValue(_ key: String, _ toggle: ToggleModel) -> Bool {
        if let v = optimistic[key]?.bool { return v }
        return toggle.value
    }

    func segmentValue(_ key: String, _ seg: SegmentedModel) -> String {
        optimistic[key]?.string ?? seg.value
    }

    func activeLanguage() -> String? {
        if let v = optimistic["active_language"] { return v.string }
        return snap?.data.recognition.language.value
    }

    func selectedModel() -> String? {
        if let v = optimistic["model"]?.string { return v }
        return snap?.data.recognition.models.first(where: \.selected)?.id
    }

    // MARK: outgoing

    private func nextReq() -> String {
        reqSeq += 1
        return "r\(reqSeq)"
    }

    @discardableResult
    func set(_ key: String, _ value: JSONValue) -> String {
        let req = nextReq()
        optimistic[key] = value
        wire.send(["type": "set", "req": req, "key": key, "value": value.any])
        return req
    }

    @discardableResult
    func action(_ name: String, _ args: [String: Any] = [:]) -> String {
        let req = nextReq()
        wire.send(["type": "action", "req": req, "name": name, "args": args])
        return req
    }

    // MARK: inbound

    func apply(_ msg: StateMessage) {
        snap = msg
        optimistic = [:]
        onWindowTitle?(msg.strings["window.title"] ?? "")

        if var ed = termEditor {
            if let req = ed.pendingReq, msg.ack == req {
                if let err = msg.errors["term"] {
                    ed.pendingReq = nil
                    ed.error = err
                    termEditor = ed
                } else {
                    termEditor = nil
                }
            } else if ed.pendingReq == nil, case .edit(let i) = ed.mode {
                // The row we edit moved or vanished (deleted elsewhere): drop the editor.
                let items = msg.data.terms.items
                if i >= items.count || items[i].heard != ed.originalHeard || items[i].wanted != ed.originalWanted {
                    termEditor = nil
                }
            } else if let err = msg.errors["term"], ed.pendingReq == nil {
                ed.error = err
                termEditor = ed
            }
        }
        if var ed = vocabEditor, let req = ed.pendingReq, msg.ack == req {
            if let err = msg.errors["vocab"] {
                ed.pendingReq = nil
                ed.error = err
                vocabEditor = ed
            } else {
                vocabEditor = nil
            }
        }
        if msg.data.calls.items.count <= 5 && callsExpanded {
            callsExpanded = false
            callQuery = ""
        }
    }

    func focus(_ name: String?) {
        if let name, let sec = Section(rawValue: name) { select(sec) }
    }

    func showToast(_ msg: ToastMessage) {
        let t = ToastState(text: msg.text, action: msg.action)
        withAnimation(T.motion(reduceMotion, 0.2)) { toast = t }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.toast?.id == t.id else { return }
                withAnimation(T.motion(self.reduceMotion, 0.2)) { self.toast = nil }
            }
        }
    }

    func runToastAction() {
        guard let a = toast?.action else { return }
        action(a.name, (a.args ?? [:]).mapValues(\.any))
        withAnimation(T.motion(reduceMotion, 0.15)) { toast = nil }
    }

    // MARK: UI-local intents

    func select(_ sec: Section) {
        menu = nil
        guard sec != section else { return }
        withAnimation(T.motion(reduceMotion)) { section = sec }
    }

    func openMenu(id: String, picker: PickerModel, current: String?) {
        if menu?.id == id { menu = nil; return }
        let idx = picker.options.firstIndex { $0.value == current && !$0.disabled }
        menu = OpenMenu(id: id, options: picker.options, current: current, highlight: idx)
    }

    func pick(_ index: Int) {
        guard let m = menu, m.options.indices.contains(index), !m.options[index].disabled else { return }
        let opt = m.options[index]
        menu = nil
        if opt.value != m.current {
            set(m.id, opt.value.map(JSONValue.string) ?? .null)
        }
    }

    private func moveHighlight(_ delta: Int) {
        guard var m = menu else { return }
        let n = m.options.count
        guard n > 0, m.options.contains(where: { !$0.disabled }) else { return }
        var i = m.highlight ?? (delta > 0 ? -1 : n)
        repeat { i = (i + delta + n) % n } while m.options[i].disabled
        m.highlight = i
        menu = m
    }

    func setHighlight(_ i: Int?) {
        guard var m = menu, m.highlight != i else { return }
        m.highlight = i
        menu = m
    }

    func copyCall(_ id: String) {
        action("call_copy", ["id": id])
        copiedCall = id
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            MainActor.assumeIsolated {
                if self?.copiedCall == id { self?.copiedCall = nil }
            }
        }
    }

    // Terms editor

    func startAdd(heard: String = "") {
        termEditor = TermEditor(mode: .add, heard: heard, wanted: "")
    }

    func startEdit(_ index: Int) {
        guard let items = snap?.data.terms.items, items.indices.contains(index) else { return }
        if case .edit(let i) = termEditor?.mode, i == index { return }
        let it = items[index]
        termEditor = TermEditor(mode: .edit(index), heard: it.heard, wanted: it.wanted,
                                originalHeard: it.heard, originalWanted: it.wanted)
    }

    func saveTerm() {
        guard var ed = termEditor, ed.pendingReq == nil else { return }
        let req: String
        switch ed.mode {
        case .add:
            req = action("term_add", ["heard": ed.heard, "wanted": ed.wanted])
        case .edit(let i):
            req = action("term_update", ["index": i, "heard": ed.heard, "wanted": ed.wanted])
        }
        ed.pendingReq = req
        ed.error = nil
        termEditor = ed
    }

    func cancelTerm() { termEditor = nil }

    // Vocabulary editor

    func saveVocab() {
        guard var ed = vocabEditor, ed.pendingReq == nil else { return }
        ed.pendingReq = action("vocab_add", ["word": ed.text])
        ed.error = nil
        vocabEditor = ed
    }

    // MARK: keyboard (called from the window's local key monitor)

    enum Key { case escape, up, down, enter }

    /// Returns true when the key was consumed.
    func handle(_ key: Key) -> Bool {
        if menu != nil {
            switch key {
            case .escape: menu = nil
            case .up: moveHighlight(-1)
            case .down: moveHighlight(1)
            case .enter: if let i = menu?.highlight { pick(i) } else { menu = nil }
            }
            return true
        }
        guard key == .escape else { return false }
        if sheetOpen {
            closeSheet()
            return true
        }
        if termEditor != nil {
            termEditor = nil
            return true
        }
        if vocabEditor != nil {
            vocabEditor = nil
            return true
        }
        return false
    }

    func openSheet() {
        sheetQuery = ""
        withAnimation(T.motion(reduceMotion, 0.2)) { sheetOpen = true }
    }

    func closeSheet() {
        withAnimation(T.motion(reduceMotion, 0.15)) { sheetOpen = false }
    }
}
