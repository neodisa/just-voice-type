// JSON Lines protocol with Python (see PROTOCOL.md): Codable models for the
// `state` snapshot, inbound message parsing and the outbound writer.

import Foundation

// MARK: - Generic JSON value (toast action args, optimistic values)

enum JSONValue: Codable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    /// Foundation object for JSONSerialization.
    var any: Any {
        switch self {
        case .null: return NSNull()
        case .bool(let b): return b
        case .number(let n): return n.rounded() == n && abs(n) < 1e15 ? Int(n) as Any : n as Any
        case .string(let s): return s
        case .array(let a): return a.map(\.any)
        case .object(let o): return o.mapValues(\.any)
        }
    }

    var string: String? { if case .string(let s) = self { return s }; return nil }
    var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    var isNull: Bool { self == .null }
}

// MARK: - Shared shapes

struct PickerOption: Decodable, Equatable {
    let value: String?
    let label: String
    let glyph: String?
    let note: String?
    let disabled: Bool
    let separatorBefore: Bool

    enum CodingKeys: String, CodingKey {
        case value, label, glyph, note, disabled
        case separatorBefore = "separator_before"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        value = try c.decodeIfPresent(String.self, forKey: .value)
        label = try c.decode(String.self, forKey: .label)
        glyph = try c.decodeIfPresent(String.self, forKey: .glyph)
        note = try c.decodeIfPresent(String.self, forKey: .note)
        disabled = try c.decodeIfPresent(Bool.self, forKey: .disabled) ?? false
        separatorBefore = try c.decodeIfPresent(Bool.self, forKey: .separatorBefore) ?? false
    }
}

struct PickerModel: Decodable, Equatable {
    let value: String?
    let caption: String?
    let disabledReason: String?
    let options: [PickerOption]

    enum CodingKeys: String, CodingKey {
        case value, caption, options
        case disabledReason = "disabled_reason"
    }
}

struct SectionLink: Decodable, Equatable {
    let label: String
    let section: String
}

struct ToggleModel: Decodable, Equatable {
    let value: Bool
    let disabledReason: String?
    let link: SectionLink?

    enum CodingKeys: String, CodingKey {
        case value, link
        case disabledReason = "disabled_reason"
    }
}

struct SegmentOption: Decodable, Equatable {
    let value: String
    let label: String
    let caption: String?
}

struct SegmentedModel: Decodable, Equatable {
    let value: String
    let disabledReason: String?
    let options: [SegmentOption]

    enum CodingKeys: String, CodingKey {
        case value, options
        case disabledReason = "disabled_reason"
    }
}

struct ModelInfo: Decodable, Equatable, Identifiable {
    let id: String
    let name: String
    let desc: String
    let size: String
    let isDefault: Bool
    let selected: Bool
    let state: String          // ready | absent | loading | downloading | error
    let progress: Double?
    let note: String?

    enum CodingKeys: String, CodingKey {
        case id, name, desc, size, selected, state, progress, note
        case isDefault = "default"
    }
}

struct CallItem: Decodable, Equatable, Identifiable {
    let id: String
    let day: String
    let time: String
    let duration: String
    let preview: String
    let missing: Bool
}

// MARK: - data

struct StatusInfo: Decodable, Equatable {
    let dot: String            // ok | rec | busy | paused | error
    let text: String
    let timerSince: Double?

    enum CodingKeys: String, CodingKey {
        case dot, text
        case timerSince = "timer_since"
    }
}

struct GeneralData: Decodable, Equatable {
    let hotkey: PickerModel
    let liveTyping: ToggleModel
    let insertMode: PickerModel
    let sounds: PickerModel
    let uiLanguage: PickerModel
    let launchAtLogin: ToggleModel
    let warning: String?

    enum CodingKeys: String, CodingKey {
        case hotkey, warning, sounds
        case liveTyping = "live_typing"
        case insertMode = "insert_mode"
        case uiLanguage = "ui_language"
        case launchAtLogin = "launch_at_login"
    }
}

struct LanguageChip: Decodable, Equatable {
    let value: String?
    let label: String
}

struct LanguageChoice: Decodable, Equatable {
    let value: String?
    let chips: [LanguageChip]
}

struct LanguageEntry: Decodable, Equatable, Identifiable {
    let code: String
    let name: String
    let english: String
    let favorite: Bool
    let locked: Bool
    var id: String { code }
}

struct Vocabulary: Decodable, Equatable {
    let items: [String]
    let enabled: Bool
}

struct RecognitionData: Decodable, Equatable {
    let models: [ModelInfo]
    let language: LanguageChoice
    let languages: [LanguageEntry]
    let smartMode: SegmentedModel
    let vocabulary: Vocabulary

    enum CodingKeys: String, CodingKey {
        case models, language, languages, vocabulary
        case smartMode = "smart_mode"
    }
}

struct CallLive: Decodable, Equatable {
    let state: String          // idle | recording | transcribing
    let startedAt: Double?

    enum CodingKeys: String, CodingKey {
        case state
        case startedAt = "started_at"
    }
}

struct CallsData: Decodable, Equatable {
    let count: Int
    let live: CallLive
    let items: [CallItem]
    let autoSupported: Bool
    let callHotkey: PickerModel
    let stealth: ToggleModel
    let detect: PickerModel
    let autoStop: ToggleModel
    let autoCapture: ToggleModel
    let device: PickerModel

    enum CodingKeys: String, CodingKey {
        case count, live, items, device, stealth, detect
        case autoSupported = "auto_supported"
        case callHotkey = "call_hotkey"
        case autoStop = "auto_stop"
        case autoCapture = "auto_capture"
    }
}

struct TermItem: Decodable, Equatable {
    let heard: String
    let wanted: String
}

struct TermsData: Decodable, Equatable {
    let items: [TermItem]
}

struct UpdateInfo: Decodable, Equatable {
    let state: String          // idle | checking | uptodate | update | error
    let text: String?
    let version: String?
}

struct AboutLink: Decodable, Equatable, Identifiable {
    let id: String
    let label: String
    let button: String
}

struct AuthorInfo: Decodable, Equatable {
    let name: String
    let github: String
}

struct AboutData: Decodable, Equatable {
    let update: UpdateInfo
    let links: [AboutLink]
    let author: AuthorInfo
}

struct AppData: Decodable, Equatable {
    let version: String
    let status: StatusInfo
    let general: GeneralData
    let recognition: RecognitionData
    let calls: CallsData
    let terms: TermsData
    let about: AboutData
}

// MARK: - Messages

struct StateMessage: Decodable, Equatable {
    let rev: Int
    let ack: String?
    let lang: String
    let strings: [String: String]
    let data: AppData
    let errors: [String: String]

    enum CodingKeys: String, CodingKey { case type, rev, ack, lang, strings, data, errors }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let type = try c.decode(String.self, forKey: .type)
        guard type == "state" else {
            throw DecodingError.dataCorruptedError(forKey: .type, in: c,
                                                   debugDescription: "expected type state, got \(type)")
        }
        rev = try c.decode(Int.self, forKey: .rev)
        // `ack` echoes our `req`, which is a string; tolerate a number too.
        if let s = try? c.decodeIfPresent(String.self, forKey: .ack) {
            ack = s
        } else if let n = try? c.decodeIfPresent(Int.self, forKey: .ack) {
            ack = String(n)
        } else {
            ack = nil
        }
        lang = try c.decode(String.self, forKey: .lang)
        strings = try c.decode([String: String].self, forKey: .strings)
        data = try c.decode(AppData.self, forKey: .data)
        errors = try c.decodeIfPresent([String: String].self, forKey: .errors) ?? [:]
    }
}

struct ToastAction: Decodable, Equatable {
    let name: String
    let label: String
    let args: [String: JSONValue]?
}

struct ToastMessage: Decodable, Equatable {
    let text: String
    let action: ToastAction?
}

private struct Envelope: Decodable { let type: String }
private struct FocusMessage: Decodable { let section: String? }

enum Inbound {
    case state(StateMessage)
    case focus(String?)
    case toast(ToastMessage)
    case quit
    case unknown(String)

    static func parse(_ line: String) throws -> Inbound {
        let data = Data(line.utf8)
        let dec = JSONDecoder()
        let env = try dec.decode(Envelope.self, from: data)
        switch env.type {
        case "state": return .state(try dec.decode(StateMessage.self, from: data))
        case "focus": return .focus(try dec.decode(FocusMessage.self, from: data).section)
        case "toast": return .toast(try dec.decode(ToastMessage.self, from: data))
        case "quit": return .quit
        default: return .unknown(env.type)
        }
    }
}

// MARK: - Output

enum Log {
    static func err(_ text: String) {
        FileHandle.standardError.write(Data(("JustVoiceTypeSettings: " + text + "\n").utf8))
    }
}

/// Writes one JSON object per line. In demo mode messages go to stderr instead
/// of stdout so nothing pretends to be talking to Python.
final class Wire: @unchecked Sendable {
    enum Target { case stdout, stderr }
    let target: Target
    private let lock = NSLock()

    init(_ target: Target) { self.target = target }

    static func encode(_ object: [String: Any]) -> Data? {
        guard JSONSerialization.isValidJSONObject(object) else { return nil }
        return try? JSONSerialization.data(withJSONObject: object,
                                           options: [.withoutEscapingSlashes, .sortedKeys])
    }

    func send(_ object: [String: Any]) {
        guard var data = Wire.encode(object) else {
            Log.err("cannot encode \(object)")
            return
        }
        lock.lock()
        defer { lock.unlock() }
        switch target {
        case .stdout:
            data.append(0x0A)
            do {
                try FileHandle.standardOutput.write(contentsOf: data)
            } catch {
                // Python is gone: nothing left to talk to.
                exit(0)
            }
        case .stderr:
            Log.err("demo → " + (String(data: data, encoding: .utf8) ?? "?"))
        }
    }
}

// MARK: - --protocol-selftest

enum ProtocolSelftest {
    /// ready → read one line → decode as `state` (exit 2 on failure) → echo action → exit 0.
    static func run() -> Int32 {
        let wire = Wire(.stdout)
        wire.send(["type": "ready"])
        guard let line = readLine(strippingNewline: true) else {
            Log.err("selftest: no input")
            return 2
        }
        do {
            _ = try JSONDecoder().decode(StateMessage.self, from: Data(line.utf8))
        } catch {
            Log.err("selftest: cannot decode state: \(error)")
            return 2
        }
        let echo = #"{"type":"action","req":"selftest","name":"check_updates","args":{}}"# + "\n"
        try? FileHandle.standardOutput.write(contentsOf: Data(echo.utf8))
        return 0
    }
}
