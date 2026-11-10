// Colour tokens («Графит») and fonts for the «Пульт» style.
// Changing the palette means changing the table below and nothing else.

import AppKit
import CoreText
import SwiftUI

enum T {
    private static func rgb(_ hex: UInt32, _ alpha: Double = 1) -> Color {
        Color(.sRGB,
              red: Double((hex >> 16) & 0xFF) / 255,
              green: Double((hex >> 8) & 0xFF) / 255,
              blue: Double(hex & 0xFF) / 255,
              opacity: alpha)
    }

    static let bg = rgb(0x0F0F0F)
    static let raise = rgb(0x262626)
    static let line = Color.white.opacity(0.10)
    static let lineStrong = Color.white.opacity(0.20)
    static let ink = rgb(0xF0F0F0)
    static let ink2 = rgb(0xB6B6B6)
    static let ink3 = rgb(0x8C8C8C)
    static let accent = rgb(0xEEEEEE)
    static let accentHover = rgb(0xFFFFFF)
    static let onAccent = rgb(0x0D0D0D)
    static let accentBg = Color.white.opacity(0.10)
    static let rec = rgb(0xEB4537)
    static let ok = rgb(0x61CB7C)
    static let danger = rgb(0xFB836D)
    static let warn = rgb(0xF0BA59)

    // Derived values used by the mockup (not separate tokens in the spec).
    static let accentLine = Color.white.opacity(0.45)   // focused field / open pop-up border
    static let display = rgb(0x060606)                  // status "display" background
    static let hover = Color.white.opacity(0.06)
    static let idleLED = rgb(0x8C8C8C)

    static let nsBg = NSColor(srgbRed: 15 / 255, green: 15 / 255, blue: 15 / 255, alpha: 1)

    static let radius: CGFloat = 3
    static let windowSize = CGSize(width: 920, height: 620)
    static let sidebarWidth: CGFloat = 196

    /// Motion: 150–200 ms ease-out (quart-like curve from the mockup).
    static func motion(_ reduce: Bool, _ duration: Double = 0.18) -> Animation {
        reduce ? .linear(duration: 0.12) : .timingCurve(0.22, 1, 0.36, 1, duration: duration)
    }
}

// MARK: - Fonts

enum Family: String {
    case ui = "Onest"
    case mono = "JetBrains Mono"
    case display = "Unbounded"
}

/// Registers the bundled variable fonts for this process and builds fonts with
/// an explicit `wght` axis value (SwiftUI's `.weight()` does not drive the
/// axis of a custom variable font reliably). Falls back to system fonts.
enum FontRegistry {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var bases: [String: CTFontDescriptor] = [:]
    nonisolated(unsafe) private static var cache: [String: Font] = [:]
    private static let wghtTag = NSNumber(value: 0x7767_6874)  // 'wght'

    static func fontDirectories() -> [URL] {
        var dirs: [URL] = []
        if let exe = Bundle.main.executableURL?.resolvingSymlinksInPath() {
            dirs.append(URL(fileURLWithPath: exe.path + "-Fonts", isDirectory: true))
        }
        // inside Just Voice Type.app the fonts live in Contents/Resources
        // (Contents/MacOS may hold only code, or codesign rejects the bundle)
        if let res = Bundle.main.resourceURL {
            dirs.append(res.appendingPathComponent("JustVoiceTypeSettings-Fonts", isDirectory: true))
        }
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
        dirs.append(cwd.appendingPathComponent("native/settings/Fonts", isDirectory: true))
        return dirs
    }

    @discardableResult
    static func registerAll() -> Bool {
        for dir in fontDirectories() {
            guard let files = try? FileManager.default.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: nil) else { continue }
            let fonts = files.filter { ["ttf", "otf"].contains($0.pathExtension.lowercased()) }
            if fonts.isEmpty { continue }
            var found: [String: CTFontDescriptor] = [:]
            for url in fonts {
                // Already-registered is fine (second launch path in the same process).
                CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
                guard let descs = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL)
                        as? [CTFontDescriptor] else { continue }
                for d in descs {
                    if let fam = CTFontDescriptorCopyAttribute(d, kCTFontFamilyNameAttribute) as? String,
                       found[fam] == nil {
                        found[fam] = d
                    }
                }
            }
            if !found.isEmpty {
                lock.lock()
                bases = found
                cache = [:]
                lock.unlock()
                return true
            }
        }
        return false
    }

    static func ctFont(_ family: Family, _ size: CGFloat, _ weight: CGFloat, italic: Bool = false) -> CTFont? {
        lock.lock()
        let base = bases[family.rawValue]
        lock.unlock()
        guard let base else { return nil }
        let attrs: [CFString: Any] = [kCTFontVariationAttribute: [wghtTag: weight]]
        let desc = CTFontDescriptorCreateCopyWithAttributes(base, attrs as CFDictionary)
        if italic {
            // None of the families ship an italic: synthesize a light oblique.
            var skew = CGAffineTransform(a: 1, b: 0, c: 0.18, d: 1, tx: 0, ty: 0)
            return CTFontCreateWithFontDescriptor(desc, size, &skew)
        }
        return CTFontCreateWithFontDescriptor(desc, size, nil)
    }

    static func font(_ family: Family, _ size: CGFloat, _ weight: CGFloat, italic: Bool = false) -> Font {
        let key = "\(family.rawValue)|\(size)|\(weight)|\(italic)"
        lock.lock()
        if let f = cache[key] { lock.unlock(); return f }
        lock.unlock()
        let f: Font
        if let ct = ctFont(family, size, weight, italic: italic) {
            f = Font(ct)
        } else {
            f = fallback(family, size, weight, italic: italic)
        }
        lock.lock()
        cache[key] = f
        lock.unlock()
        return f
    }

    /// Line height SwiftUI uses for one line of this font (ascent + descent + leading).
    static func naturalLineHeight(_ family: Family, _ size: CGFloat, _ weight: CGFloat) -> CGFloat {
        if let f = ctFont(family, size, weight) {
            return CTFontGetAscent(f) + CTFontGetDescent(f) + CTFontGetLeading(f)
        }
        return (NSFont.systemFont(ofSize: size).ascender - NSFont.systemFont(ofSize: size).descender).rounded(.up)
    }

    private static func fallback(_ family: Family, _ size: CGFloat, _ weight: CGFloat, italic: Bool) -> Font {
        let w: Font.Weight = weight >= 600 ? .semibold : weight >= 500 ? .medium : .regular
        var f: Font
        switch family {
        case .mono: f = .system(size: size, weight: w, design: .monospaced)
        case .ui, .display: f = .system(size: size, weight: w, design: .default)
        }
        if italic { f = f.italic() }
        return f
    }
}

/// Short-hands used by every view.
enum F {
    static func ui(_ size: CGFloat = 13.5, _ weight: CGFloat = 400, italic: Bool = false) -> Font {
        FontRegistry.font(.ui, size, weight, italic: italic)
    }
    static func mono(_ size: CGFloat = 12, _ weight: CGFloat = 500) -> Font {
        FontRegistry.font(.mono, size, weight)
    }
    static func display(_ size: CGFloat = 30, _ weight: CGFloat = 600) -> Font {
        FontRegistry.font(.display, size, weight)
    }
    /// SF Symbols are drawn at 13 pt regular (spec «Иконки»).
    static func icon(_ size: CGFloat = 13) -> Font { .system(size: size, weight: .regular) }
}

extension View {
    /// Sets the font and a CSS-like `line-height` (multiplier): the extra
    /// leading goes between lines and, as half-leading, above and below.
    func type(_ family: Family, _ size: CGFloat, _ weight: CGFloat = 400,
              lh: CGFloat = 1.45, italic: Bool = false) -> some View {
        let extra = size * lh - FontRegistry.naturalLineHeight(family, size, weight)
        return self
            .font(FontRegistry.font(family, size, weight, italic: italic))
            .lineSpacing(max(0, extra))
            .padding(.vertical, extra / 2)
    }
}
