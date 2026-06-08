---
paths:
  - "**/Modifiers/**"
  - "**/*Modifier.swift"
---

# Modifiers

ViewModifiers encapsulate reusable view transformations. Check your shared component library and app-specific modifiers before creating new ones — if a solved problem exists, use it or update it.

## When to Create a Modifier

- The same combination of modifiers appears 3+ times across different views
- A behavior needs to be toggled or parameterized (e.g., conditional styling, environment-dependent effects)
- Complex gesture + animation logic that would bloat a view body

Don't create a modifier for a one-off transformation or something that's clearer inline.

## Structure

Name: `*Modifier.swift`. Always pair with a View extension for clean call-site syntax:

```swift
struct CardBackgroundModifier: ViewModifier { ... }

extension View {
    func cardBackground(radius: CGFloat = 20) -> some View {
        modifier(CardBackgroundModifier(radius: radius))
    }
}
```

## Conventions

- Modifiers read from environment, not from direct bindings to parent state
- Use `@Environment(\.colorScheme)` for adaptive styling, not passed-in booleans
- iOS version branching (`#available(iOS 26, *)`) belongs in modifiers, not in views — keep views clean
- Modifier order matters: Layout → Appearance → Effects → Interaction → Environment
