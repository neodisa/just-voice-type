// «Звонки»: recent calls (live row, empty state, expanded list with search and
// day headers) and recording settings.

import SwiftUI

struct CallsSection: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        if let c = store.snap?.data.calls {
            SectionHeader(title: store.s("nav.calls"),
                          count: c.count > 0 ? String(c.count) : nil,
                          lede: store.s("calls.lede"))

            GroupHeader(title: store.s(store.callsExpanded ? "calls.group.all" : "calls.group.recent")) {
                if !c.items.isEmpty {
                    LinkButton(title: store.s("calls.open_folder"), leading: "folder") {
                        store.action("calls_open_folder")
                    }
                }
            }
            if store.callsExpanded {
                SearchField(placeholder: store.s("calls.search"), text: $store.callQuery, autofocus: true)
                    .padding(.bottom, 10)
            }
            Box { CallList(calls: c) }

            GroupHeader(store.s("calls.group.recording"))
            if !c.autoSupported {
                Notice(icon: "exclamationmark.triangle",
                       title: store.s("calls.unsupported.title"),
                       caption: store.s("calls.unsupported.caption"),
                       link: InlineLink(label: store.s("calls.unsupported.howto"),
                                        url: Route.link("call_setup")))
                    .padding(.bottom, 12)
            }
            Box {
                PickerRow(label: store.s("calls.hotkey"), key: "call_hotkey", picker: c.callHotkey, keyStyle: true)
                RowSep()
                ToggleRow(label: store.s("calls.auto"), caption: store.s("calls.auto.caption"),
                          key: "auto_system_audio", toggle: c.autoCapture)
                RowSep()
                PickerRow(label: store.s("calls.device"), key: "call_device", picker: c.device,
                          noneLabel: store.s("calls.device.none"))
            }
            NoteText(text: store.s("calls.consent"))
        }
    }
}

private struct CallList: View {
    @EnvironmentObject private var store: Store
    let calls: CallsData

    var body: some View {
        let live = calls.live.state
        let hasLive = live == "recording" || live == "transcribing"
        VStack(alignment: .leading, spacing: 0) {
            if live == "recording" {
                LiveCallRow(startedAt: calls.live.startedAt)
            } else if live == "transcribing" {
                TranscribingRow()
            }
            if calls.items.isEmpty {
                if !hasLive { emptyState }
            } else if store.callsExpanded {
                expanded(hasLive: hasLive)
            } else {
                ForEach(Array(calls.items.prefix(5).enumerated()), id: \.element.id) { i, item in
                    if i > 0 || hasLive { RowSep() }
                    CallRow(item: item, grouped: false)
                }
                if calls.items.count > 5 {
                    RowSep()
                    HStack(spacing: 0) {
                        LinkButton(title: store.s("calls.show_all", n: calls.count), trailing: "chevron.down") {
                            store.callsExpanded = true
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(8)
                }
            }
        }
    }

    private var emptyState: some View {
        EmptyState(icon: "phone", title: store.s("calls.empty.title"), caption: store.s("calls.empty.caption")) {
            ConsoleButton(title: store.s("calls.empty.record"), icon: "mic", kind: .primary) {
                store.action("call_toggle")
            }
        }
    }

    @ViewBuilder
    private func expanded(hasLive: Bool) -> some View {
        let q = store.callQuery.trimmingCharacters(in: .whitespaces)
        let shown = calls.items.filter { q.isEmpty || $0.preview.localizedCaseInsensitiveContains(q) }
        if shown.isEmpty {
            if hasLive { RowSep() }
            EmptyState(caption: store.s("calls.search.empty", q: q)) { EmptyView() }
        } else {
            ForEach(Array(shown.enumerated()), id: \.element.id) { i, item in
                let newDay = i == 0 || shown[i - 1].day != item.day
                if i > 0 || hasLive { RowSep() }
                if newDay {
                    Text(item.day)
                        .font(F.mono(12, 500))
                        .foregroundColor(T.ink3)
                        .padding(.horizontal, 14)
                        .padding(.top, 14)
                        .padding(.bottom, 6)
                    RowSep()
                }
                CallRow(item: item, grouped: true)
            }
        }
        RowSep()
        HStack(spacing: 0) {
            LinkButton(title: store.s("calls.collapse")) {
                store.callsExpanded = false
                store.callQuery = ""
            }
        }
        .frame(maxWidth: .infinity)
        .padding(8)
    }
}

private struct CallRow: View {
    @EnvironmentObject private var store: Store
    let item: CallItem
    let grouped: Bool
    @State private var hover = false

    var body: some View {
        let copied = store.copiedCall == item.id
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 1) {
                Text(grouped ? item.time : "\(item.day), \(item.time)")
                    .font(F.mono(12.5, 500)).foregroundColor(T.ink).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                Text(item.duration).font(F.mono(12, 400)).foregroundColor(T.ink3)
            }
            .frame(width: 140, alignment: .leading)
            Text(item.missing ? store.s("calls.missing") : item.preview)
                .foregroundColor(item.missing ? T.ink3 : T.ink2)
                .lineLimit(2)
                .type(.ui, 13.5, lh: 1.4, italic: item.missing)
                .frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: 2) {
                IconButton(symbol: copied ? "checkmark" : "doc.on.doc",
                           help: store.s(copied ? "calls.copied" : "calls.copy"),
                           tint: copied ? T.ok : nil, disabled: item.missing) {
                    store.copyCall(item.id)
                }
                IconButton(symbol: "doc.text", help: store.s("calls.open"), disabled: item.missing) {
                    store.action("call_open", ["id": item.id])
                }
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .padding(.vertical, 10)
        .background(hover ? Color.white.opacity(0.03) : Color.clear)
        .onHover { hover = $0 }
    }
}

private struct LiveCallRow: View {
    @EnvironmentObject private var store: Store
    let startedAt: Double?

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    RecDot(size: 8)
                    Text(store.s("calls.live.recording")).font(F.mono(12.5, 500)).foregroundColor(T.ink)
                        .lineLimit(1)
                }
                Group {
                    if let startedAt {
                        ElapsedText(since: startedAt)
                    } else {
                        Text(" ")
                    }
                }
                .font(F.mono(12, 400))
                .foregroundColor(T.ink)
            }
            .frame(width: 140, alignment: .leading)
            Text(store.s("calls.live.recording.caption"))
                .foregroundColor(T.ink2).lineLimit(2)
                .type(.ui, 13.5, lh: 1.4)
                .frame(maxWidth: .infinity, alignment: .leading)
            ConsoleButton(title: store.s("calls.live.stop"), icon: "stop.fill") {
                store.action("call_toggle")
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .padding(.vertical, 10)
        .overlay { Rectangle().strokeBorder(T.accent, lineWidth: 1) }
    }
}

private struct TranscribingRow: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Spinner(size: 13)
            Text(store.s("calls.live.transcribing")).font(F.ui(13.5)).foregroundColor(T.ink2)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 48)
    }
}
