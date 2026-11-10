// «О программе»: version, update check, links, author.

import SwiftUI

struct AboutSection: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        if let d = store.snap?.data {
            let about = d.about
            SectionHeader(title: store.has("about.title") ? store.s("about.title") : "Just Voice Type",
                          count: d.version,
                          lede: store.s("about.lede"))
                .padding(.bottom, 26)

            Box { UpdateRow(update: about.update) }

            GroupHeader(store.s("about.group.links"))
            Box {
                ForEach(Array(about.links.enumerated()), id: \.element.id) { i, link in
                    if i > 0 { RowSep() }
                    SettingRow(label: link.label) {
                        LinkButton(title: link.button, trailing: "arrow.up.right") {
                            store.action("open_link", ["id": link.id])
                        }
                    }
                }
            }

            GroupHeader(store.s("about.group.author"))
            Box {
                SettingRow(label: about.author.name, caption: store.s("about.author.caption")) {
                    LinkButton(title: about.author.github,
                               leading: "chevron.left.forwardslash.chevron.right",
                               trailing: "arrow.up.right") {
                        store.action("open_link", ["id": "github"])
                    }
                }
            }
            NoteText(text: store.s("about.copyright"))
        }
    }
}

private struct UpdateRow: View {
    @EnvironmentObject private var store: Store
    let update: UpdateInfo

    var body: some View {
        switch update.state {
        case "update":
            HStack(alignment: .center, spacing: 20) {
                VStack(alignment: .leading, spacing: 2) {
                    availableLabel
                    CaptionText(text: update.text,
                                link: InlineLink(label: store.s("about.update.whatsnew"),
                                                 url: Route.link("releases")))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                ConsoleButton(title: store.s("about.update.download"), icon: "arrow.down.circle", kind: .primary) {
                    store.action("open_link", ["id": "update"])
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(T.accentBg)
        case "error":
            SettingRow(label: store.s("about.group.updates"), error: update.text) {
                ConsoleButton(title: store.s("about.update.retry"), icon: "arrow.clockwise") {
                    store.action("check_updates")
                }
            }
        case "checking":
            SettingRow(label: store.s("about.group.updates"), caption: update.text) {
                ConsoleButton(title: store.s("about.update.check"), disabled: true, spinning: true) {}
            }
        default:  // idle, uptodate
            SettingRow(label: store.s("about.group.updates"), caption: update.text) {
                ConsoleButton(title: store.s("about.update.check"), icon: "arrow.clockwise") {
                    store.action("check_updates")
                }
            }
        }
    }

    /// «Доступна версия 0.15.0» with the version number in mono, like the mockup.
    private var availableLabel: Text {
        let label = store.has("about.update.available") ? store.s("about.update.available") : (update.version ?? "")
        if let v = update.version, !v.isEmpty, let r = label.range(of: v) {
            let head = Text(verbatim: String(label[..<r.lowerBound])).font(F.ui(13.5))
            let ver = Text(verbatim: v).font(F.mono(13, 500))
            let tail = Text(verbatim: String(label[r.upperBound...])).font(F.ui(13.5))
            return Text("\(head)\(ver)\(tail)").foregroundColor(T.ink)
        }
        return Text(verbatim: label).font(F.ui(13.5)).foregroundColor(T.ink)
    }
}
