// «Термины»: search, add, inline edit of «Слышится → Пишется» pairs.

import SwiftUI

struct TermsSection: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        if let terms = store.snap?.data.terms {
            let items = terms.items
            let adding = store.termEditor?.mode == .add
            SectionHeader(title: store.s("nav.terms"),
                          count: items.isEmpty ? nil : String(items.count),
                          lede: store.s("terms.lede"))
                .padding(.bottom, 26)

            if !items.isEmpty || adding {
                HStack(spacing: 8) {
                    SearchField(placeholder: store.s("terms.search"), text: $store.termQuery)
                    ConsoleButton(title: store.s("terms.add"), icon: "plus", kind: .primary, height: 34) {
                        store.startAdd()
                    }
                }
                .padding(.bottom, 10)
            }
            Box { TermList(items: items) }
            if !items.isEmpty {
                NoteText(text: store.s("terms.note"))
            }
        }
    }
}

private struct TermList: View {
    @EnvironmentObject private var store: Store
    let items: [TermItem]

    var body: some View {
        let q = store.termQuery.trimmingCharacters(in: .whitespaces)
        let rows = items.enumerated().filter { _, t in
            q.isEmpty || (t.heard + " " + t.wanted).localizedCaseInsensitiveContains(q)
        }
        let adding = store.termEditor?.mode == .add
        VStack(alignment: .leading, spacing: 0) {
            if adding {
                TermEditorRow()
            }
            if items.isEmpty {
                if !adding {
                    EmptyState(icon: "character.book.closed",
                               title: store.s("terms.empty.title"),
                               caption: store.s("terms.empty.caption")) {
                        ConsoleButton(title: store.s("terms.empty.add"), icon: "plus", kind: .primary) {
                            store.startAdd()
                        }
                    }
                }
            } else if rows.isEmpty {
                if adding { RowSep() }
                EmptyState(caption: store.s("terms.search.empty", q: q)) {
                    ConsoleButton(title: store.s("terms.search.add", q: q), icon: "plus") {
                        store.startAdd(heard: q)
                        store.termQuery = ""
                    }
                }
            } else {
                ForEach(Array(rows.enumerated()), id: \.element.offset) { n, row in
                    if n > 0 || adding { RowSep() }
                    if case .edit(let i) = store.termEditor?.mode, i == row.offset {
                        TermEditorRow()
                    } else {
                        TermRow(index: row.offset, item: row.element)
                    }
                }
            }
        }
    }
}

private struct TermRow: View {
    @EnvironmentObject private var store: Store
    let index: Int
    let item: TermItem
    @State private var hover = false

    var body: some View {
        HStack(spacing: 10) {
            Text(item.heard).foregroundColor(T.ink2).lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "arrow.right").font(F.icon(11)).foregroundColor(T.ink3).frame(width: 20)
            Text(item.wanted).foregroundColor(T.ink).lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            IconButton(symbol: "xmark", help: store.s("terms.delete")) {
                store.action("term_delete", ["index": index])
            }
            .opacity(hover ? 1 : 0)
        }
        .font(F.ui(13.5))
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .padding(.vertical, 7)
        .background(hover ? Color.white.opacity(0.025) : Color.clear)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .onTapGesture { store.startEdit(index) }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

private struct TermEditorRow: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        let ed = store.termEditor
        let heard = Binding(get: { store.termEditor?.heard ?? "" }, set: { store.termEditor?.heard = $0 })
        let wanted = Binding(get: { store.termEditor?.wanted ?? "" }, set: { store.termEditor?.wanted = $0 })
        let err = ed?.error ?? store.error("term")
        let busy = ed?.pendingReq != nil
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                EditField(placeholder: store.s("terms.heard"), text: heard,
                          bad: err != nil && (ed?.heard.isEmpty ?? false),
                          autofocus: (ed?.heard.isEmpty ?? true) || ed?.mode != .add,
                          onSubmit: { store.saveTerm() })
                Image(systemName: "arrow.right").font(F.icon(11)).foregroundColor(T.ink3).frame(width: 20)
                EditField(placeholder: store.s("terms.wanted"), text: wanted,
                          bad: err != nil && (ed?.wanted.isEmpty ?? false),
                          autofocus: !(ed?.heard.isEmpty ?? true) && ed?.mode == .add,
                          onSubmit: { store.saveTerm() })
                HStack(spacing: 6) {
                    ConsoleButton(title: store.s("terms.save"), kind: .primary, disabled: busy) {
                        store.saveTerm()
                    }
                    ConsoleButton(title: store.s("terms.cancel")) { store.cancelTerm() }
                }
            }
            if let err {
                ErrorLine(text: err).padding(.horizontal, 2)
            }
        }
        .padding(8)
        .background(Color.white.opacity(0.03))
    }
}
