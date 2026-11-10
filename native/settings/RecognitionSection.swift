// «Распознавание»: model list, speech language chips (+ sheet), text
// processing mode, recognition hints (vocabulary).

import SwiftUI

struct RecognitionSection: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        if let r = store.snap?.data.recognition {
            SectionHeader(title: store.s("nav.recognition"), lede: store.s("recognition.lede"))

            GroupHeader(store.s("recognition.group.model"))
            Box {
                ForEach(Array(r.models.enumerated()), id: \.element.id) { i, m in
                    if i > 0 { RowSep() }
                    ModelRow(model: m)
                }
                if let e = store.error("model") {
                    RowSep()
                    ErrorLine(text: e).padding(.horizontal, 14).padding(.vertical, 10)
                }
            }

            GroupHeader(title: store.s("recognition.group.language")) {
                LinkButton(title: store.s("recognition.language.more"), trailing: "chevron.right") {
                    store.openSheet()
                }
            }
            Box {
                VStack(alignment: .leading, spacing: 0) {
                    CaptionText(text: store.s("recognition.language.caption"))
                    FlowLayout(spacing: 6, lineSpacing: 6) {
                        ForEach(Array(r.language.chips.enumerated()), id: \.offset) { _, chip in
                            Chip(label: chip.label, selected: chip.value == store.activeLanguage()) {
                                if chip.value != store.activeLanguage() {
                                    store.set("active_language", chip.value.map(JSONValue.string) ?? .null)
                                }
                            }
                        }
                    }
                    .padding(.top, 10)
                    if let e = store.error("active_language") {
                        ErrorLine(text: e).padding(.top, 8)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
            }

            GroupHeader(store.s("recognition.group.processing"))
            Box {
                SmartModeRow(seg: r.smartMode)
                RowSep()
                VocabRow(vocab: r.vocabulary)
            }
        }
    }
}

private struct ModelRow: View {
    @EnvironmentObject private var store: Store
    let model: ModelInfo
    @State private var hover = false

    var body: some View {
        let selected = store.selectedModel() == model.id
        HStack(alignment: .center, spacing: 12) {
            RadioMark(on: selected)
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(model.name).foregroundColor(T.ink).type(.ui, 13.5, 500)
                    if model.isDefault {
                        Text(store.s("recognition.model.default")).font(F.ui(12)).foregroundColor(T.ink3)
                    }
                }
                detail.padding(.top, 2)
                if model.state == "downloading" {
                    LEDProgress(value: model.progress ?? 0)
                        .frame(maxWidth: 320)
                        .padding(.top, 8)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            meta
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .background(hover ? Color.white.opacity(0.03) : Color.clear)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .onTapGesture {
            if !selected { store.set("model", .string(model.id)) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder private var detail: some View {
        let text = model.note ?? model.desc
        switch model.state {
        case "error":
            ErrorLine(text: text)
        case "loading":
            HStack(alignment: .center, spacing: 6) {
                Spinner(size: 12)
                CaptionText(text: text)
            }
        default:
            CaptionText(text: text)
        }
    }

    @ViewBuilder private var meta: some View {
        switch model.state {
        case "absent":
            ConsoleButton(title: model.size, icon: "arrow.down.circle") {
                store.set("model", .string(model.id))
            }
        case "error":
            ConsoleButton(title: store.s("recognition.model.retry"), icon: "arrow.clockwise") {
                store.action("model_retry", ["id": model.id])
            }
        default:
            Text(model.size).font(F.mono(12, 400)).foregroundColor(T.ink3)
        }
    }
}

private struct SmartModeRow: View {
    @EnvironmentObject private var store: Store
    let seg: SegmentedModel

    var body: some View {
        let value = store.segmentValue("smart_mode", seg)
        let caption = seg.disabledReason ?? seg.options.first { $0.value == value }?.caption
        SettingRow(label: store.s("recognition.mode"), caption: caption,
                   error: store.error("smart_mode"), alignTop: true) {
            Segmented(options: seg.options, value: value, disabled: seg.disabledReason != nil) {
                store.set("smart_mode", .string($0))
            }
        }
    }
}

private struct VocabRow: View {
    @EnvironmentObject private var store: Store
    let vocab: Vocabulary

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(store.s("recognition.vocab")).foregroundColor(T.ink).type(.ui, 13.5)
            CaptionText(text: store.s("recognition.vocab.caption")).padding(.top, 2)
            FlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(Array(vocab.items.enumerated()), id: \.offset) { i, word in
                    TagChip(label: word, dim: !vocab.enabled, removeHelp: store.s("terms.delete")) {
                        store.action("vocab_remove", ["index": i])
                    }
                }
                if store.vocabEditor != nil {
                    VocabInput()
                } else {
                    AddChip(label: store.s("recognition.vocab.add")) {
                        store.vocabEditor = VocabEditor()
                    }
                }
            }
            .padding(.top, 10)
            if let err = store.vocabEditor?.error ?? (store.vocabEditor != nil ? store.error("vocab") : nil) {
                ErrorLine(text: err).padding(.top, 8)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }
}

private struct VocabInput: View {
    @EnvironmentObject private var store: Store
    @State private var focused = false

    var body: some View {
        let text = Binding(
            get: { store.vocabEditor?.text ?? "" },
            set: { store.vocabEditor?.text = $0 })
        let bad = store.vocabEditor?.error != nil
        InputField(placeholder: store.s("recognition.vocab.placeholder"), text: text,
                   font: F.mono(12, 500), autofocus: true,
                   onSubmit: { store.saveVocab() },
                   onFocus: { focused = $0 })
            .padding(.horizontal, 11)
            .frame(width: 140, height: 24)
            .overlay {
                RoundedRectangle(cornerRadius: T.radius)
                    .strokeBorder(bad ? T.danger : T.accentLine, lineWidth: 1)
            }
    }
}
