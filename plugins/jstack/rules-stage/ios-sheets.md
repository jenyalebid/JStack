---
paths:
  - "**/Sheets/**"
  - "**/*Sheet.swift"
  - "**/*Sheet*.swift"
---

# Sheets

A sheet is a modal surface over the current content. Choose the right block for the user intent, then apply the app's design language within those constraints.

## Blocks

### Confirm Action
User makes a binary decision mid-flow (pause, quit, delete). No time to browse — act or dismiss.

- Detent: `.medium` or custom `.height()`
- No NavigationStack, no nav title
- No DismissButton — the buttons ARE the dismiss
- 2 buttons max per row, horizontally stacked
- Optional: toolbar overflow menu for secondary actions
- Varies: button style, icon/mascot content, animation, color theme

### Info Browse
User explores detailed content (chapters, stats, details, layouts).

- Detent: `.large`
- NavigationStack + `.navigationBarTitleDisplayMode(.inline)`
- DismissButton in toolbar
- Content: List with sections
- Optional: toolbar actions (share, edit)
- Varies: section content, row design, header treatment

### Edit Form
User modifies and saves data.

- NavigationStack + inline title
- Save + Cancel in toolbar (`.confirmationAction` / `.cancellationAction`) — no xmark
- `.interactiveDismissDisabled(hasChanges)` when there are unsaved changes
- Content: Form or List with input fields
- Destructive actions in own section at bottom with confirmation dialog
- Varies: field types, validation rules, save behavior

### Value Picker
User selects a single value (page number, progress, time, date).

- Detent: custom `.height()` fitted to content
- NavigationStack + title
- Confirm button at bottom (not toolbar)
- Optional: secondary menu in toolbar for related actions
- Varies: picker style (wheel, segmented), value range

### Share Preview
User previews content and shares it.

- Detent: `.large`
- NavigationStack + DismissButton
- Content: List with centered card preview in section (`.listRowBackground(Color.clear)`)
- ShareLink pinned to bottom via `.safeAreaInset(edge: .bottom)` with `PrimaryActionButtonStyle`
- ImageRenderer at scale 3 for export, rendered on `.onAppear` + `.onChange`
- Optional: editable message, style picker in additional sections
- Varies: card design, share data, preview options

### Info Confirm
User sees context, then optionally acts. Can walk away without acting.

- Detent: `.medium` or custom `.height()`
- DismissButton (xmark) — user can dismiss without acting
- Single primary action button at bottom via `.safeAreaInset(edge: .bottom)` with `PrimaryActionButtonStyle`
- Content: centered informational/emotional content
- Varies: content tone, icon/imagery, action label

## Fundamentals

### Bottom-Pinned Actions
Any primary action button pinned via `.safeAreaInset(edge: .bottom)` uses `PrimaryActionButtonStyle()` (JSwiftUI). This applies to all sheet blocks — Share Preview, Info Confirm, or any custom layout with a bottom action.

### Detent Selection
Default to a single detent. `.medium` for compact content. `.large` for scrollable. Custom `.height()` for specific fit. Multi-detent `[.medium, .large]` is rare — use only when genuinely needed. `.presentationContentInteraction(.scrolls)` if scrolling at `.medium` shouldn't expand.

### Presentation Routing
Use `PresentationController` (JSwiftUI) for routing, not ad-hoc `@State var showSheet`. One source of truth. Keep presentation modifiers (detent, background) on the call site — the parent decides sizing, the sheet decides content.

### Environment Propagation
`.presentationController(for:)` must be **innermost**. Environment injections **outermost**. Sheets/fullScreenCovers create new view hierarchies — modifiers inside the controller's scope propagate, modifiers outside do not.

### Sheet Placement
Attach `.sheet` to a **stable, long-lived parent** — the List, the outermost container, or the body root. Never on Group (fires per-child), ForEach items (recreated on scroll), or phantom views.

### Style
Follow the project's background convention. iOS 26 Liquid Glass is automatic — don't override. Drag indicator when detent isn't obvious. `.presentationDragIndicator(.visible)` for multi-detent.
