---
paths:
  - "**/Screens/**"
  - "**/*Screen.swift"
---

# Screens

A screen is a navigation destination — somewhere the user "is." Tabs, pushed views, deep link targets. Not a component, not a sheet, not a cell.

## Blocks

### Tab Root
Primary destination in the tab bar. The "home" of a navigation stack.

- Large navigation title (default display mode)
- Own NavigationStack provided by the tab container — don't create another
- Content: ScrollView + LazyVStack for section-based layouts
- Must handle 4 states: loading (skeleton/shimmer), empty (ContentUnavailableView + action), error (message + retry), content
- `.refreshable {}` if content is server-fetched
- `.searchable()` if content is large enough to filter (~20+ items)
- Varies: section layout, header treatment, content density

### Detail Push
Drilled-into content via NavigationLink. User navigated here from a parent.

- Inline navigation title (`.navigationBarTitleDisplayMode(.inline)`)
- Inherits NavigationStack from parent — don't create another
- Toolbar actions in `.topBarTrailing` for the primary action
- Content: ScrollView or List depending on structure
- Varies: content layout, toolbar actions, detail depth

## Fundamentals

### Content States
Every screen that loads data handles all four states. An empty list is not a blank screen — show why it's empty and what the user can do about it. Use `ContentUnavailableView` (iOS 17+).

### Toolbar
- Top-trailing: primary action (add, edit, filter)
- Top-leading: secondary or back (back is automatic)
- Keep toolbar items concise — icon-only or short labels
- One action per `ToolbarItem` — never cram multiple buttons into one item with HStack
- Logically separate groups with `ToolbarSpacer(placement:)` on iOS 26:
  ```swift
  ToolbarItem(placement: .topBarLeading) { shareButton }
  if #available(iOS 26.0, *) {
      ToolbarSpacer(placement: .topBarLeading)
  }
  ToolbarItem(placement: .topBarLeading) { helpButton }
  ```

### Search
Place `.searchable()` on the scrollable content inside the NavigationStack. Filtered empty state should explain why ("No results for 'fantasy'") and offer to clear filters.
