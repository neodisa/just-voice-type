// Building blocks of the «Пульт» style: group boxes, rows, key caps, pop-up
// pickers, square toggles, segmented control, buttons, LED progress, fields,
// empty states, toast. Everything is flat: no shadows, glows, gradients, blur.

import SwiftUI

// MARK: - Snapshot mode (--render-dir)

/// `.live` is the real window. In the snapshot modes AppKit-backed views
/// (TextField, ScrollView) are swapped for static look-alikes, because
/// ImageRenderer draws placeholders for them.
enum SnapshotMode { case live, window, full }

private struct SnapshotModeKey: EnvironmentKey {
    static let defaultValue: SnapshotMode = .live
}

extension EnvironmentValues {
    var snapshotMode: SnapshotMode {
        get { self[SnapshotModeKey.self] }
        set { self[SnapshotModeKey.self] = newValue }
    }
}

// MARK: - Lines

struct HLine: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.midY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.midY))
        return p
    }
}

/// 1 pt dashed horizontal rule.
struct DashedRule: View {
    var color: Color = T.lineStrong
    var body: some View {
        HLine().stroke(color, style: StrokeStyle(lineWidth: 1, dash: [3, 3])).frame(height: 1)
    }
}

/// Dashed separator between rows of a group.
struct RowSep: View {
    var body: some View { DashedRule(color: T.line) }
}

// MARK: - Group box

/// Group: `lineStrong` frame, dashed top edge, corner ticks top-left and bottom-right.
struct Box<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .padding(.top, 3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(1)
            .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
            .overlay(alignment: .top) {
                HLine()
                    .stroke(T.ink, style: StrokeStyle(lineWidth: 3, dash: [8, 5]))
                    .frame(height: 3)
                    .padding(.horizontal, 1)
                    .padding(.top, 1)
            }
            .overlay { CornerTicks() }
    }
}

struct CornerTicks: View {
    var body: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            Path { p in
                p.addRect(CGRect(x: -1, y: -1, width: 2, height: 7))
                p.addRect(CGRect(x: -1, y: -1, width: 7, height: 2))
                p.addRect(CGRect(x: w - 1, y: h - 6, width: 2, height: 7))
                p.addRect(CGRect(x: w - 6, y: h - 1, width: 7, height: 2))
            }
            .fill(T.ink2)
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Headers

struct SectionHeader: View {
    let title: String
    var count: String? = nil
    var countIsVersion = false
    let lede: String

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(title)
                    .tracking(-0.6)
                    .foregroundColor(T.ink)
                    .lineLimit(1)
                    .type(.display, 30, 600, lh: 1.1)
                if let count {
                    Text(count).font(F.mono(15, 400)).foregroundColor(T.ink)
                }
            }
            Text(lede)
                .foregroundColor(T.ink2)
                .type(.ui, 13.5)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 540, alignment: .leading)
                .padding(.top, 6)
                .padding(.bottom, 22)
                .overlay(alignment: .bottom) { Rectangle().fill(T.lineStrong).frame(height: 1) }
        }
    }
}

struct GroupHeader<Trailing: View>: View {
    let title: String
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: 10) {
                Text(title).foregroundColor(T.ink2).type(.mono, 12, 500, lh: 1.3).fixedSize()
                DashedRule()
            }
            trailing
        }
        .frame(minHeight: 16)
        .padding(.horizontal, 2)
        .padding(.top, 26)
        .padding(.bottom, 8)
    }
}

extension GroupHeader where Trailing == EmptyView {
    init(_ title: String) {
        self.title = title
        self.trailing = EmptyView()
    }
}

// MARK: - Text bits

/// An inline text link inside a caption. Routed through `openURL` (jvt://…).
struct InlineLink {
    let label: String
    let url: URL
}

enum Route {
    static func section(_ s: String) -> URL { URL(string: "jvt://section/\(s)")! }
    static func link(_ id: String) -> URL { URL(string: "jvt://link/\(id)")! }
}

struct CaptionText: View {
    let text: String?
    var link: InlineLink? = nil
    var color: Color = T.ink2
    var maxWidth: CGFloat = 447   // 56ch of Onest 12

    var body: some View {
        Text(attributed)
            .foregroundColor(color)
            .tint(T.accent)
            .type(.ui, 12)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: maxWidth, alignment: .leading)
    }

    private var attributed: AttributedString {
        var a = AttributedString(text ?? "")
        if let link {
            if !a.characters.isEmpty { a += AttributedString(" ") }
            var l = AttributedString(link.label)
            l.link = link.url
            l.foregroundColor = T.accent
            a += l
        }
        return a
    }
}

struct ErrorLine: View {
    let text: String
    var color: Color = T.danger
    var icon = "exclamationmark.circle"

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: icon).font(F.icon(12))
            Text(text).type(.ui, 12).fixedSize(horizontal: false, vertical: true)
        }
        .font(F.ui(12))
        .foregroundColor(color)
        .frame(maxWidth: 447, alignment: .leading)
    }
}

struct NoteText: View {
    let text: String
    var body: some View {
        Text(text)
            .foregroundColor(T.ink3)
            .type(.ui, 12)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: 495, alignment: .leading)   // 62ch
            .padding(.horizontal, 2)
            .padding(.top, 14)
    }
}

// MARK: - Row

struct SettingRow<Trailing: View>: View {
    let label: String?
    var caption: String? = nil
    var link: InlineLink? = nil
    var error: String? = nil
    var alignTop = false
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: alignTop ? .top : .center, spacing: 20) {
            VStack(alignment: .leading, spacing: 0) {
                if let label {
                    Text(label).foregroundColor(T.ink).type(.ui, 13.5)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if caption != nil || link != nil {
                    CaptionText(text: caption, link: link).padding(.top, 2)
                }
                if let error {
                    ErrorLine(text: error).padding(.top, 4)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            trailing
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }
}

// MARK: - Key cap

struct KeyCap: View {
    let text: String
    var color: Color = T.lineStrong

    var body: some View {
        Text(text)
            .font(F.mono(12, 500))
            .lineLimit(1)
            .padding(.horizontal, 6)
            .frame(minHeight: 16)
            .padding(.bottom, 1)
            .overlay { RoundedRectangle(cornerRadius: 2).strokeBorder(color, lineWidth: 1) }
            .overlay(alignment: .bottom) {
                Rectangle().fill(color).frame(height: 1).padding(.horizontal, 1).padding(.bottom, 1)
            }
            .fixedSize()
    }
}

/// Option label: glyph as a key cap before the label (protocol rule). Key
/// pickers draw a glyph-less label itself as a key cap (`F13`, mockup).
struct OptionLabel: View {
    let glyph: String?
    let label: String
    var keyStyle = false
    var capColor: Color = T.lineStrong

    var body: some View {
        HStack(spacing: 7) {
            if let glyph, !glyph.isEmpty {
                KeyCap(text: glyph, color: capColor)
                Text(label).lineLimit(1)
            } else if keyStyle {
                KeyCap(text: label, color: capColor)
            } else {
                Text(label).lineLimit(1)
            }
        }
    }
}

// MARK: - Pop-up picker

struct PopAnchorKey: PreferenceKey {
    static let defaultValue: [String: Anchor<CGRect>] = [:]
    static func reduce(value: inout [String: Anchor<CGRect>], nextValue: () -> [String: Anchor<CGRect>]) {
        value.merge(nextValue()) { $1 }
    }
}

struct PopupButton: View {
    @EnvironmentObject private var store: Store
    let key: String
    let picker: PickerModel
    var keyStyle = false
    var noneLabel: String? = nil
    @State private var hover = false

    var body: some View {
        let current = store.pickerValue(key, picker)
        let opt = picker.options.first { $0.value == current }
        let disabled = picker.disabledReason != nil
        let open = store.menu?.id == key
        Button {
            store.openMenu(id: key, picker: picker, current: current)
        } label: {
            HStack(spacing: 8) {
                if let opt {
                    OptionLabel(glyph: opt.glyph, label: opt.label, keyStyle: keyStyle)
                } else {
                    Text(noneLabel ?? current ?? "—").lineLimit(1)
                }
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 10, weight: .regular))
                    .foregroundColor(T.ink3)
            }
            .font(F.mono(12, 500))
            .foregroundColor(T.ink)
            .padding(.leading, 10)
            .padding(.trailing, 8)
            .frame(height: 28)
            .background(Color.white.opacity(hover && !disabled ? 0.10 : 0.06))
            .overlay {
                RoundedRectangle(cornerRadius: T.radius)
                    .strokeBorder(open ? T.accentLine : T.lineStrong, lineWidth: 1)
            }
            .clipShape(RoundedRectangle(cornerRadius: T.radius))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.45 : 1)
        .onHover { hover = $0 }
        .fixedSize()
        .anchorPreference(key: PopAnchorKey.self, value: .bounds) { [key: $0] }
    }
}

/// The open pop-up menu, drawn at window level next to its button.
struct MenuPanel: View {
    @EnvironmentObject private var store: Store
    let menu: OpenMenu

    static func estimatedHeight(_ m: OpenMenu) -> CGFloat {
        let seps = m.options.enumerated().filter { $0.offset > 0 && $0.element.separatorBefore }.count
        return 8 + CGFloat(m.options.count) * 26 + CGFloat(seps) * 9
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(menu.options.enumerated()), id: \.offset) { i, opt in
                if opt.separatorBefore && i > 0 {
                    Rectangle().fill(T.line).frame(height: 1).padding(.vertical, 4).padding(.horizontal, 2)
                }
                item(i, opt)
            }
        }
        .padding(4)
        .frame(minWidth: 220, alignment: .leading)
        .fixedSize()
        .background(T.raise)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
        .clipShape(RoundedRectangle(cornerRadius: T.radius))
    }

    private func item(_ i: Int, _ opt: PickerOption) -> some View {
        let lit = menu.highlight == i && !opt.disabled
        let fg = lit ? T.onAccent : T.ink
        return HStack(spacing: 8) {
            Image(systemName: "checkmark")
                .font(F.icon(11))
                .frame(width: 14)
                .opacity(opt.value == menu.current ? 1 : 0)
            OptionLabel(glyph: opt.glyph, label: opt.label,
                        capColor: lit ? T.onAccent.opacity(0.35) : T.lineStrong)
            Spacer(minLength: 14)
            if let note = opt.note {
                Text(note).font(F.mono(12, 400)).foregroundColor(lit ? T.onAccent.opacity(0.75) : T.ink3)
            }
        }
        .font(F.mono(12.5, 500))
        .foregroundColor(fg)
        .padding(.horizontal, 8)
        .frame(height: 26)
        .background(lit ? T.accent : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 2))
        .opacity(opt.disabled ? 0.45 : 1)
        .contentShape(Rectangle())
        .onHover { inside in if inside && !opt.disabled { store.setHighlight(i) } }
        .onTapGesture { store.pick(i) }
    }
}

// MARK: - Toggle, segmented, radio, checkbox

struct SquareToggle: View {
    let isOn: Bool
    var disabled = false
    let action: (Bool) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button { action(!isOn) } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                RoundedRectangle(cornerRadius: 2).fill(isOn ? T.accent : Color.clear)
                RoundedRectangle(cornerRadius: 2).strokeBorder(isOn ? T.accent : T.lineStrong, lineWidth: 1)
                RoundedRectangle(cornerRadius: 2)
                    .fill(isOn ? T.onAccent : T.ink3)
                    .frame(width: 12, height: 12)
                    .padding(3)
            }
            .frame(width: 34, height: 18)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.4 : 1)
        .animation(reduceMotion ? nil : T.motion(false), value: isOn)
        .accessibilityAddTraits(.isToggle)
        .accessibilityValue(isOn ? "1" : "0")
    }
}

struct Segmented: View {
    let options: [SegmentOption]
    let value: String
    var disabled = false
    let action: (String) -> Void

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(options.enumerated()), id: \.offset) { i, opt in
                if i > 0 { Rectangle().fill(T.lineStrong).frame(width: 1) }
                SegmentButton(label: opt.label, selected: opt.value == value) {
                    if opt.value != value { action(opt.value) }
                }
            }
        }
        .fixedSize()
        .padding(1)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
        .clipShape(RoundedRectangle(cornerRadius: T.radius))
        .disabled(disabled)
        .opacity(disabled ? 0.45 : 1)
    }
}

private struct SegmentButton: View {
    let label: String
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(F.mono(12, 500))
                .foregroundColor(selected ? T.onAccent : hover ? T.ink : T.ink2)
                .padding(.horizontal, 12)
                .frame(height: 28)
                .background(selected ? T.accent : Color.clear)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

struct RadioMark: View {
    let on: Bool
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 2).strokeBorder(on ? T.accent : T.ink3, lineWidth: 1.5)
            if on { RoundedRectangle(cornerRadius: 1).fill(T.accent).frame(width: 8, height: 8) }
        }
        .frame(width: 16, height: 16)
    }
}

struct CheckMark: View {
    let on: Bool
    var body: some View {
        ZStack {
            if on {
                RoundedRectangle(cornerRadius: 2).fill(T.accent)
                Image(systemName: "checkmark")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(T.onAccent)
            } else {
                RoundedRectangle(cornerRadius: 2).strokeBorder(T.ink3, lineWidth: 1.5)
            }
        }
        .frame(width: 16, height: 16)
    }
}

// MARK: - Buttons

enum ButtonKind { case normal, primary, danger }

struct ConsoleButton: View {
    let title: String
    var icon: String? = nil
    var kind: ButtonKind = .normal
    var disabled = false
    var spinning = false
    var height: CGFloat = 28
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if spinning {
                    Spinner(size: 12, color: fg)
                } else if let icon {
                    Image(systemName: icon).font(F.icon(12))
                }
                Text(title).lineLimit(1)
            }
            .font(F.mono(12, 500))
            .padding(.horizontal, 11)
            .frame(height: height)
            .contentShape(Rectangle())
        }
        .buttonStyle(ConsoleButtonStyle(kind: kind, hover: hover && !disabled))
        .disabled(disabled)
        .opacity(disabled ? 0.5 : 1)
        .onHover { hover = $0 }
        .fixedSize()
    }

    private var fg: Color {
        switch kind {
        case .primary: return T.onAccent
        case .danger: return T.danger
        case .normal: return T.ink
        }
    }
}

struct ConsoleButtonStyle: ButtonStyle {
    let kind: ButtonKind
    let hover: Bool

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed
        let fg: Color
        let bg: Color
        let border: Color
        switch kind {
        case .primary:
            fg = T.onAccent
            bg = pressed ? T.ink2 : hover ? T.accentHover : T.accent
            border = .clear
        case .danger:
            fg = T.danger
            bg = pressed ? T.raise : hover ? Color.white.opacity(0.07) : .clear
            border = T.danger.opacity(0.4)
        case .normal:
            fg = T.ink
            bg = pressed ? T.raise : hover ? Color.white.opacity(0.07) : .clear
            border = T.lineStrong
        }
        return configuration.label
            .foregroundColor(fg)
            .background(bg)
            .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(border, lineWidth: 1) }
            .clipShape(RoundedRectangle(cornerRadius: T.radius))
    }
}

struct LinkButton: View {
    let title: String
    var leading: String? = nil
    var trailing: String? = nil
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if let leading { Image(systemName: leading).font(F.icon(11)) }
                Text(title).underline(hover)
                if let trailing { Image(systemName: trailing).font(.system(size: 9, weight: .semibold)) }
            }
            .font(F.ui(12))
            .foregroundColor(hover ? T.accentHover : T.accent)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .fixedSize()
    }
}

struct IconButton: View {
    let symbol: String
    var help: String = ""
    var tint: Color? = nil
    var disabled = false
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(F.icon(13))
                .foregroundColor(tint ?? (hover && !disabled ? T.ink : T.ink2))
                .frame(width: 28, height: 28)
                .background(hover && !disabled ? Color.white.opacity(0.08) : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: T.radius))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.35 : 1)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

// MARK: - Chips

struct Chip: View {
    let label: String
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(F.mono(12, 500))
                .foregroundColor(selected ? T.onAccent : T.ink2)
                .padding(.horizontal, 11)
                .frame(height: 24)
                .background(selected ? T.accent : hover ? T.hover : Color.clear)
                .overlay {
                    RoundedRectangle(cornerRadius: T.radius)
                        .strokeBorder(selected ? T.accent : T.lineStrong, lineWidth: 1)
                }
                .clipShape(RoundedRectangle(cornerRadius: T.radius))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

struct TagChip: View {
    let label: String
    var dim = false
    var removeHelp = ""
    let onRemove: () -> Void
    @State private var hover = false

    var body: some View {
        HStack(spacing: 4) {
            Text(label).font(F.mono(12, 500)).foregroundColor(dim ? T.ink2 : T.ink)
            Button(action: onRemove) {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(hover ? T.ink : T.ink3)
                    .frame(width: 16, height: 16)
                    .background(hover ? Color.white.opacity(0.10) : Color.clear)
                    .clipShape(RoundedRectangle(cornerRadius: 2))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .onHover { hover = $0 }
            .help(removeHelp)
        }
        .padding(.leading, 11)
        .padding(.trailing, 5)
        .frame(height: 24)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
    }
}

struct AddChip: View {
    let label: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: "plus").font(.system(size: 10, weight: .regular))
                Text(label)
            }
            .font(F.mono(12, 500))
            .foregroundColor(hover ? T.ink : T.ink3)
            .padding(.horizontal, 11)
            .frame(height: 24)
            .background(hover ? T.hover : Color.clear)
            .overlay {
                RoundedRectangle(cornerRadius: T.radius)
                    .strokeBorder(T.lineStrong, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

// MARK: - Indicators

struct LEDSegments: Shape {
    var segment: CGFloat = 5
    var gap: CGFloat = 2
    func path(in r: CGRect) -> Path {
        var p = Path()
        var x = r.minX
        while x < r.maxX {
            p.addRect(CGRect(x: x, y: r.minY, width: min(segment, r.maxX - x), height: r.height))
            x += segment + gap
        }
        return p
    }
}

/// Segmented "LED" progress bar; the fill is scaled with `scaleEffect(x:)`.
struct LEDProgress: View {
    let value: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let v = max(0, min(1, value))
        ZStack(alignment: .leading) {
            LEDSegments().fill(Color.white.opacity(0.10))
            Rectangle()
                .fill(T.accent)
                .scaleEffect(x: v, y: 1, anchor: .leading)
                .mask(LEDSegments())
        }
        .frame(height: 8)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.4), value: v)
        .accessibilityValue("\(Int(v * 100)) %")
    }
}

/// Loader ring (3/4 arc). Rotates; under Reduce Motion it only pulses opacity.
struct Spinner: View {
    var size: CGFloat = 13
    var color: Color = T.ink2
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.snapshotMode) private var snapshot

    var body: some View {
        if snapshot != .live {
            arc
        } else {
            TimelineView(.animation) { ctx in
                let t = ctx.date.timeIntervalSinceReferenceDate
                arc
                    .rotationEffect(.degrees(reduceMotion ? 0 : (t * 400).truncatingRemainder(dividingBy: 360)))
                    .opacity(reduceMotion ? 0.55 + 0.45 * abs(sin(t * 2)) : 1)
            }
        }
    }

    private var arc: some View {
        Circle()
            .trim(from: 0, to: 0.75)
            .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
            .frame(width: size - 3, height: size - 3)
            .frame(width: size, height: size)
    }
}

/// Recording dot: blinks 1 s steps(2); steady under Reduce Motion.
struct RecDot: View {
    var size: CGFloat = 8
    var cornerRadius: CGFloat? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.snapshotMode) private var snapshot

    var body: some View {
        if reduceMotion || snapshot != .live {
            dot(on: true)
        } else {
            TimelineView(.periodic(from: .now, by: 0.5)) { ctx in
                dot(on: Int(ctx.date.timeIntervalSinceReferenceDate * 2) % 2 == 0)
            }
        }
    }

    private func dot(on: Bool) -> some View {
        Group {
            if let r = cornerRadius {
                RoundedRectangle(cornerRadius: r).fill(T.rec)
            } else {
                Circle().fill(T.rec)
            }
        }
        .frame(width: size, height: size)
        .opacity(on ? 1 : 0.25)
    }
}

enum Clock {
    static func format(_ seconds: Double) -> String {
        let t = max(0, Int(seconds))
        return "\(t / 60):" + String(format: "%02d", t % 60)
    }
}

/// `prefix` + m:ss since `since` (epoch seconds), ticking every second.
struct ElapsedText: View {
    let since: Double
    var prefix = ""

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            Text(prefix + Clock.format(ctx.date.timeIntervalSince1970 - since))
        }
    }
}

// MARK: - Fields

struct InputField: View {
    let placeholder: String
    @Binding var text: String
    var font: Font = F.ui(13.5)
    var autofocus = false
    var onSubmit: () -> Void = {}
    var onFocus: (Bool) -> Void = { _ in }
    @FocusState private var focused: Bool
    @Environment(\.snapshotMode) private var snapshot

    var body: some View {
        if snapshot != .live {
            Text(text.isEmpty ? placeholder : text)
                .font(font)
                .foregroundColor(text.isEmpty ? T.ink3 : T.ink)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            TextField("", text: $text, prompt: Text(placeholder).foregroundColor(T.ink3))
                .textFieldStyle(.plain)
                .font(font)
                .foregroundColor(T.ink)
                .focused($focused)
                .onSubmit(onSubmit)
                .onChange(of: focused) { _, now in onFocus(now) }
                .onAppear {
                    if autofocus { DispatchQueue.main.async { focused = true } }
                }
        }
    }
}

struct SearchField: View {
    let placeholder: String
    @Binding var text: String
    var autofocus = false
    @State private var focused = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").font(F.icon(13)).foregroundColor(T.ink3)
            InputField(placeholder: placeholder, text: $text, autofocus: autofocus,
                       onFocus: { focused = $0 })
        }
        .padding(.horizontal, 10)
        .frame(height: 34)
        .overlay {
            RoundedRectangle(cornerRadius: T.radius)
                .strokeBorder(focused ? T.accentLine : T.line, lineWidth: 1)
        }
    }
}

/// Bordered field of the inline term editor.
struct EditField: View {
    let placeholder: String
    @Binding var text: String
    var bad = false
    var autofocus = false
    var onSubmit: () -> Void = {}
    @State private var focused = false

    var body: some View {
        InputField(placeholder: placeholder, text: $text, autofocus: autofocus,
                   onSubmit: onSubmit, onFocus: { focused = $0 })
            .padding(.horizontal, 8)
            .frame(height: 28)
            .background(T.bg)
            .overlay {
                RoundedRectangle(cornerRadius: T.radius)
                    .strokeBorder(bad ? T.danger : focused ? T.accentLine : T.lineStrong, lineWidth: 1)
            }
    }
}

// MARK: - Empty state, notice

struct EmptyState<Action: View>: View {
    var icon: String? = nil
    var title: String? = nil
    let caption: String
    @ViewBuilder var action: Action

    var body: some View {
        VStack(spacing: 10) {
            if let icon {
                Image(systemName: icon)
                    .font(F.icon(17))
                    .foregroundColor(T.ink2)
                    .frame(width: 36, height: 36)
                    .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
            }
            if let title {
                Text(title)
                    .font(F.display(15, 600))
                    .foregroundColor(T.ink)
                    .multilineTextAlignment(.center)
            }
            Text(caption)
                .foregroundColor(T.ink2)
                .multilineTextAlignment(.center)
                .type(.ui, 13.5)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 395)   // 44ch
            action
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 28)
        .frame(maxWidth: .infinity)
    }
}

struct Notice: View {
    var icon = "exclamationmark.triangle"
    var iconColor: Color = T.warn
    var title: String? = nil
    let caption: String
    var captionColor: Color = T.ink2
    var link: InlineLink? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon).font(F.icon(13)).foregroundColor(iconColor).padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                if let title { Text(title).foregroundColor(T.ink).type(.ui, 13.5) }
                CaptionText(text: caption, link: link, color: captionColor, maxWidth: 520)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(Color.white.opacity(0.03))
        .overlay {
            RoundedRectangle(cornerRadius: T.radius)
                .strokeBorder(T.lineStrong, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
        }
    }
}

// MARK: - Flow layout (chips)

struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    private func lines(_ maxWidth: CGFloat, _ subviews: Subviews) -> [[(Int, CGSize)]] {
        var out: [[(Int, CGSize)]] = [[]]
        var x: CGFloat = 0
        for (i, s) in subviews.enumerated() {
            let sz = s.sizeThatFits(.unspecified)
            if x > 0 && x + sz.width > maxWidth {
                out.append([])
                x = 0
            }
            out[out.count - 1].append((i, sz))
            x += sz.width + spacing
        }
        return out
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        let ls = lines(maxW, subviews)
        var h: CGFloat = 0
        var w: CGFloat = 0
        for (n, line) in ls.enumerated() {
            let lh = line.map(\.1.height).max() ?? 0
            h += lh + (n > 0 ? lineSpacing : 0)
            let lw = line.map(\.1.width).reduce(0, +) + spacing * CGFloat(max(0, line.count - 1))
            w = max(w, lw)
        }
        return CGSize(width: proposal.width ?? w, height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for line in lines(bounds.width, subviews) {
            let lh = line.map(\.1.height).max() ?? 0
            var x = bounds.minX
            for (i, sz) in line {
                subviews[i].place(at: CGPoint(x: x, y: y + (lh - sz.height) / 2),
                                  proposal: ProposedViewSize(sz))
                x += sz.width + spacing
            }
            y += lh + lineSpacing
        }
    }
}

// MARK: - Toast

struct ToastView: View {
    @EnvironmentObject private var store: Store
    let toast: ToastState

    var body: some View {
        HStack(spacing: 14) {
            Text(toast.text).font(F.ui(13.5)).foregroundColor(T.ink).lineLimit(1)
            if let a = toast.action {
                ConsoleButton(title: a.label, icon: "arrow.uturn.backward") { store.runToastAction() }
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, toast.action == nil ? 14 : 8)
        .frame(minHeight: 44)
        .background(T.raise)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
        .clipShape(RoundedRectangle(cornerRadius: T.radius))
    }
}
