// Window layout: sidebar with nav "keys" and the status display, the section
// pane, and window-level overlays (pop-up menu, language sheet, toast).

import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: Store
    @Environment(\.snapshotMode) private var snapshot
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack(alignment: .topLeading) {
            HStack(spacing: 0) {
                Sidebar()
                Rectangle().fill(T.lineStrong).frame(width: 1)
                MainPane()
            }
            .overlayPreferenceValue(PopAnchorKey.self) { anchors in
                MenuLayer(anchors: anchors)
            }

            if store.sheetOpen {
                LanguageSheet()
                    .transition(.opacity)
                    .zIndex(2)
            }
            if let toast = store.toast {
                VStack {
                    Spacer()
                    ToastView(toast: toast).padding(.bottom, 16)
                }
                .frame(maxWidth: .infinity)
                .transition(reduceMotion ? .opacity : .opacity.combined(with: .offset(y: 6)))
                .zIndex(3)
            }
            if snapshot != .live {
                FakeTrafficLights()
            }
        }
        .background(T.bg)
        .environment(\.openURL, OpenURLAction { url in
            store.route(url)
            return .handled
        })
    }
}

extension Store {
    /// jvt://section/<name> selects a section; jvt://link/<id> asks Python to open it.
    func route(_ url: URL) {
        guard url.scheme == "jvt", let host = url.host else { return }
        let arg = url.lastPathComponent
        switch host {
        case "section": focus(arg)
        case "link": action("open_link", ["id": arg])
        default: break
        }
    }
}

/// Traffic lights are window chrome; draw stand-ins only in --render-dir output.
private struct FakeTrafficLights: View {
    var body: some View {
        HStack(spacing: 8) {
            ForEach(0..<3, id: \.self) { _ in
                Circle().fill(Color.white.opacity(0.16)).frame(width: 12, height: 12)
            }
        }
        .padding(.leading, 16)
        .padding(.top, 17)
    }
}

// MARK: - Sidebar

private struct Sidebar: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            nav(.general, "nav.general")
            nav(.recognition, "nav.recognition")
            nav(.calls, "nav.calls")
            nav(.terms, "nav.terms", badge: termsBadge)
            Spacer(minLength: 8)
            nav(.about, "nav.about")
            if let status = store.snap?.data.status {
                StatusDisplay(status: status).padding(.top, 4)
            }
        }
        .padding(.top, 56)
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
        .frame(width: T.sidebarWidth - 1)
        .frame(maxHeight: .infinity)
        .opacity(store.snap == nil ? 0 : 1)
    }

    private var termsBadge: String? {
        guard let n = store.snap?.data.terms.items.count, n > 0 else { return nil }
        return String(n)
    }

    private func nav(_ sec: Section, _ key: String, badge: String? = nil) -> some View {
        NavKey(label: store.s(key), badge: badge, selected: store.section == sec) {
            store.select(sec)
        }
    }
}

private struct NavKey: View {
    let label: String
    let badge: String?
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Circle()
                    .fill(selected ? T.accent : T.idleLED)
                    .frame(width: 6, height: 6)
                Text(label)
                    .font(F.mono(12.5, 500))
                    .foregroundColor(selected || hover ? T.ink : T.ink2)
                    .lineLimit(1)
                Spacer(minLength: 4)
                if let badge {
                    Text(badge).font(F.mono(12, 400)).foregroundColor(T.ink3)
                }
            }
            .padding(.horizontal, 10)
            .frame(height: 34)
            .background(hover && !selected ? Color.white.opacity(0.045) : Color.clear)
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

private struct StatusDisplay: View {
    let status: StatusInfo

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            dot
            Group {
                if let since = status.timerSince {
                    ElapsedText(since: since, prefix: status.text + " · ")
                } else {
                    Text(status.text)
                }
            }
            .foregroundColor(T.ink)
            .type(.mono, 12, 500, lh: 1.3)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 9)
        .frame(minHeight: 36)
        .background(T.display)
        .overlay { RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.lineStrong, lineWidth: 1) }
        .clipShape(RoundedRectangle(cornerRadius: T.radius))
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private var dot: some View {
        switch status.dot {
        case "rec": RecDot(size: 7, cornerRadius: 1)
        default:
            RoundedRectangle(cornerRadius: 1).fill(color).frame(width: 7, height: 7)
        }
    }

    private var color: Color {
        switch status.dot {
        case "ok": return T.ok
        case "busy": return T.warn
        case "error": return T.danger
        case "rec": return T.rec
        default: return T.ink3   // paused
        }
    }
}

// MARK: - Main pane

private struct MainPane: View {
    @EnvironmentObject private var store: Store
    @Environment(\.snapshotMode) private var snapshot
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            if store.snap == nil {
                Color.clear
            } else if snapshot == .live {
                ScrollView(.vertical) {
                    content
                }
                .scrollIndicators(.automatic)
                .id(store.section)
                .transition(.asymmetric(
                    insertion: reduceMotion ? .opacity : .opacity.combined(with: .offset(y: 4)),
                    removal: .identity))
            } else if snapshot == .window {
                // Overlay so an overflowing section cannot grow the pane.
                Color.clear
                    .overlay(alignment: .top) { content.fixedSize(horizontal: false, vertical: true) }
                    .clipped()
            } else {
                content.fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch store.section {
            case .general: GeneralSection()
            case .recognition: RecognitionSection()
            case .calls: CallsSection()
            case .terms: TermsSection()
            case .about: AboutSection()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 44)
        .padding(.horizontal, 44)
        .padding(.bottom, 56)
    }
}

// MARK: - Pop-up menu layer

private struct MenuLayer: View {
    @EnvironmentObject private var store: Store
    let anchors: [String: Anchor<CGRect>]

    var body: some View {
        GeometryReader { proxy in
            if let m = store.menu, let a = anchors[m.id] {
                let r = proxy[a]
                let h = MenuPanel.estimatedHeight(m)
                let below = r.maxY + 4
                let above = r.minY - 4 - h
                let bottom = proxy.size.height - 8
                // Below the button if it fits, else above, else as low as the window allows.
                let y = below + h <= bottom ? below : above >= 8 ? above : max(8, bottom - h)
                ZStack(alignment: .topLeading) {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { store.menu = nil }
                    HStack(spacing: 0) {
                        Spacer(minLength: 0)
                        MenuPanel(menu: m)
                    }
                    .frame(width: max(r.maxX, 240))
                    .offset(y: y)
                }
                .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
            }
        }
    }
}
