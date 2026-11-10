// «Основное»: dictation key, live typing, insert mode, UI language, login item.

import SwiftUI

struct GeneralSection: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        if let g = store.snap?.data.general {
            SectionHeader(title: store.s("nav.general"), lede: store.s("general.lede"))

            GroupHeader(store.s("general.group.dictation"))
            if let w = g.warning {
                Notice(caption: w, captionColor: T.warn).padding(.bottom, 10)
            }
            Box {
                PickerRow(label: store.s("general.hotkey"), key: "hotkey", picker: g.hotkey, keyStyle: true)
                RowSep()
                ToggleRow(label: store.s("general.live"), caption: store.s("general.live.caption"),
                          key: "live_typing", toggle: g.liveTyping)
                RowSep()
                PickerRow(label: store.s("general.insert"), key: "insert_mode", picker: g.insertMode)
            }

            GroupHeader(store.s("general.group.app"))
            Box {
                PickerRow(label: store.s("general.ui_language"), key: "ui_language", picker: g.uiLanguage)
                RowSep()
                ToggleRow(label: store.s("general.login"), caption: nil,
                          key: "launch_at_login", toggle: g.launchAtLogin)
            }
        }
    }
}

/// Row with a pop-up picker. `disabled_reason` replaces the caption.
struct PickerRow: View {
    @EnvironmentObject private var store: Store
    let label: String
    let key: String
    let picker: PickerModel
    var keyStyle = false
    var noneLabel: String? = nil

    var body: some View {
        SettingRow(label: label,
                   caption: picker.disabledReason ?? picker.caption,
                   error: store.error(key)) {
            PopupButton(key: key, picker: picker, keyStyle: keyStyle, noneLabel: noneLabel)
        }
    }
}

/// Row with a square toggle. `disabled_reason` replaces the caption and the
/// optional `link` selects another section.
struct ToggleRow: View {
    @EnvironmentObject private var store: Store
    let label: String
    let caption: String?
    let key: String
    let toggle: ToggleModel

    var body: some View {
        let reason = toggle.disabledReason
        let link = reason == nil ? nil : toggle.link.map {
            InlineLink(label: $0.label, url: Route.section($0.section))
        }
        SettingRow(label: label, caption: reason ?? caption, link: link, error: store.error(key)) {
            SquareToggle(isOn: store.toggleValue(key, toggle), disabled: reason != nil) { now in
                store.set(key, .bool(now))
            }
            .accessibilityLabel(label)
        }
    }
}
