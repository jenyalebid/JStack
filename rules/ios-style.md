---
paths:
  - "Books-Project/**/*.swift"
  - "Wordy-Project/**/*.swift"
  - "Gamebit-Project/**/*.swift"
  - "Packages/**/*.swift"
---

# iOS Design Foundations

Universal design principles for all J&J iOS projects. These are the baseline — component-type rules (sheets, lists, screens, etc.) provide specific patterns and load automatically by directory.

Full HIG reference: `~/Research/apple-hig-ios-swiftui-reference.md`

## Typography

- Use system text styles (`.title`, `.body`, `.caption`, etc.) — they scale with Dynamic Type automatically
- Bold for hierarchy, color for semantics. Don't use color to create text hierarchy
- `.monospacedDigit()` on numeric values that change (counters, stats, timers)
- Minimum 11pt (`.caption2`). Never smaller
- Max 3-4 text style levels per screen

## Color

- Semantic colors for text: `.primary`, `.secondary`, `Color(uiColor: .tertiaryLabel)`
- Custom colors in xcassets with light + dark variants. No hardcoded RGB
- One accent/tint color per app
- Status: `.red` (error), `.green` (success), `.orange` (warning), `.blue` (info)
- Always verify in both light and dark mode

## Spacing

- Scale: **4** (tight) · **8** (related) · **12** (standard) · **16** (section/padding) · **20** (margin)
- `.padding()` = 16pt. `.padding(.horizontal, 20)` for screen edges
- `@ScaledMetric` when spacing should scale with Dynamic Type
- Respect safe areas. `.ignoresSafeArea()` only for background fills

## Accessibility

- 44x44pt minimum touch targets
- Accessibility labels on all interactive elements
- 4.5:1 contrast ratio (normal text), 3:1 (large text)
- `.accessibilityHidden(true)` on decorative images

## Platform

- iOS 18 minimum, iOS 26 focus
- `NavigationStack` for all new navigation (not `NavigationView`)
- Push for content hierarchy, modal for self-contained tasks
- Liquid Glass (iOS 26) is automatic — don't override system materials
- `if #available(iOS 26, *)` for new APIs, keep paths cleanly separated

### iOS 26 Known Issues
- **Toolbar labels in NavigationStack**: Labels and custom views in `.toolbar` may render invisible or clipped on iOS 26 (Liquid Glass). Apply `.fixedSize()` to toolbar content (Labels, Text, HStacks) to force correct sizing. Always verify toolbar content is visible in screenshots — code looking correct does not mean it renders correctly.
- **Non-interactive toolbar items**: Liquid Glass gives all toolbar items a glass outline that makes them look like buttons. For informational content (labels, stats, text) use `.sharedBackgroundVisibility(.hidden)` on the ToolbarItem to remove the glass outline. Only actual buttons should have the outline.

## View Composition

- Max ~30-40 lines per view body — extract subviews
- Check project components + shared packages before creating new UI
- Modifier order: Layout → Appearance → Effects → Interaction → Environment

## Type Safety — No AnyView

`AnyView` is **banned** in J&J SwiftUI code. It erases static view type, breaks SwiftUI's structural diffing, and degrades animations / transitions / identity-based features (`matchedGeometryEffect`, `@FocusState`, scroll position).

- **Container with content slot:** make it generic — `struct Foo<Card: View>: View { @ViewBuilder var card: () -> Card }`. Never store `() -> AnyView`. `ImageRenderer` / `UIHostingController` accept the generic content directly.
- **Heterogeneous view kinds:** use a `@ViewBuilder` `switch` over an enum, or a typed snapshot struct holding each row. See `StatView.PatternSnapshot` and `GameHeaderView` "Slot dispatch (no AnyView)" for reference shape.
- **Code review:** AnyView is a guideline violation, not a style nit. Fix during review.
- **Escape hatch:** truly heterogeneous user-config-driven trees only. Must be justified in a comment. Default is no.
