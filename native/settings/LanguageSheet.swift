// «Ещё языки…» sheet: dropped from the top of the window over a scrim.
// Search, checkboxes (checked = favourite), count, «Готово». Esc closes.

import SwiftUI

struct LanguageSheet: View {
    @EnvironmentObject private var store: Store
    @Environment(\.snapshotMode) private var snapshot
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let rowHeight: CGFloat = 31
    private static let maxListHeight: CGFloat = 318

    var body: some View {
        let langs = store.snap?.data.recognition.languages ?? []
        let q = store.sheetQuery.trimmingCharacters(in: .whitespaces)
        let shown = langs.filter {
            q.isEmpty || ($0.name + " " + $0.english).localizedCaseInsensitiveContains(q)
        }
        let favorites = langs.filter(\.favorite).count

        ZStack(alignment: .top) {
            Color.black.opacity(0.45)
                .contentShape(Rectangle())
                .onTapGesture { store.closeSheet() }

            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(store.s("recognition.sheet.title")).font(F.ui(15, 600)).foregroundColor(T.ink)
                    CaptionText(text: store.s("recognition.sheet.caption"))
                    SearchField(placeholder: store.s("recognition.sheet.search"),
                                text: $store.sheetQuery, autofocus: true)
                        .padding(.top, 8)
                }
                .padding(.horizontal, 18)
                .padding(.top, 18)
                .padding(.bottom, 10)

                list(shown)
                    .overlay(alignment: .top) { Rectangle().fill(T.line).frame(height: 1) }
                    .overlay(alignment: .bottom) { Rectangle().fill(T.line).frame(height: 1) }

                HStack {
                    Text(store.s("recognition.sheet.count", n: favorites))
                        .font(F.ui(12)).foregroundColor(T.ink2)
                    Spacer()
                    ConsoleButton(title: store.s("recognition.sheet.done"), kind: .primary) {
                        store.closeSheet()
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 12)
            }
            .frame(width: 440)
            .background(
                UnevenRoundedRectangle(cornerRadii: .init(bottomLeading: T.radius, bottomTrailing: T.radius))
                    .fill(T.bg))
            .overlay { SheetBorder().stroke(T.lineStrong, lineWidth: 1) }
            .transition(reduceMotion ? .opacity : .opacity.combined(with: .offset(y: -16)))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    @ViewBuilder
    private func list(_ shown: [LanguageEntry]) -> some View {
        if shown.isEmpty {
            Text(store.s("recognition.sheet.empty"))
                .font(F.ui(13.5)).foregroundColor(T.ink2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 20)
                .padding(.vertical, 28)
        } else {
            let height = min(CGFloat(shown.count) * Self.rowHeight, Self.maxListHeight)
            Group {
                if snapshot == .live {
                    ScrollView(.vertical) { rows(shown) }
                } else {
                    rows(shown).frame(height: height, alignment: .top).clipped()
                }
            }
            .frame(height: height)
        }
    }

    private func rows(_ shown: [LanguageEntry]) -> some View {
        VStack(spacing: 0) {
            ForEach(shown) { lang in
                LanguageRow(lang: lang)
            }
        }
    }
}

private struct LanguageRow: View {
    @EnvironmentObject private var store: Store
    let lang: LanguageEntry
    @State private var hover = false

    var body: some View {
        HStack(spacing: 10) {
            CheckMark(on: lang.favorite).opacity(lang.locked ? 0.45 : 1)
            Text(lang.name).font(F.ui(13.5)).foregroundColor(T.ink).lineLimit(1)
            Spacer(minLength: 8)
            Text(lang.english).font(F.ui(12)).foregroundColor(T.ink3).lineLimit(1)
        }
        .padding(.horizontal, 18)
        .frame(height: 31)
        .background(hover && !lang.locked ? Color.white.opacity(0.04) : Color.clear)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .onTapGesture {
            if !lang.locked { store.action("favorite_toggle", ["code": lang.code]) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(lang.favorite ? [.isButton, .isSelected] : .isButton)
    }
}

/// Sheet frame without the top edge (it hangs from the titlebar), square top
/// corners and 3 pt bottom corners.
private struct SheetBorder: Shape {
    func path(in rect: CGRect) -> Path {
        let r = rect.insetBy(dx: 0.5, dy: 0)
        let c = T.radius
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addLine(to: CGPoint(x: r.minX, y: r.maxY - 0.5 - c))
        p.addQuadCurve(to: CGPoint(x: r.minX + c, y: r.maxY - 0.5), control: CGPoint(x: r.minX, y: r.maxY - 0.5))
        p.addLine(to: CGPoint(x: r.maxX - c, y: r.maxY - 0.5))
        p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.maxY - 0.5 - c), control: CGPoint(x: r.maxX, y: r.maxY - 0.5))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        return p
    }
}
