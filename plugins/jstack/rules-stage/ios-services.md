---
paths:
  - "**/Services/**"
  - "**/*Service.swift"
  - "**/*Repository.swift"
  - "**/*Coordinator.swift"
  - "**/*Calculator.swift"
---

# Services

Non-UI logic: data fetching, business rules, scheduling, calculations, API integrations. No SwiftUI imports.

## Conventions

- Services don't import SwiftUI — they produce data, views consume it
- Use `@Observable` classes for services that views need to observe (injected via `.environment()`)
- Use plain classes or enums with static methods for stateless utilities
- Use actors for services that manage concurrent state (network fetchers, data coordinators)
- Singletons (`.shared`) only for truly global services (repository, event manager). Prefer environment injection.

## Error Handling

- Services define their own error types, not raw strings
- Errors propagate to the view layer — views decide how to present them
- Network services use `async throws` — callers handle failure

## @State and @Observable Init Safety

Objects stored in `@State` must have **side-effect-free** `init()`. SwiftUI recreates the default expression (`@State private var foo = Foo()`) on every view struct body evaluation — `@State` discards the duplicate but the init's side effects still fire. If `init()` mutates `@Observable` state, it triggers re-render, which re-evaluates body, which calls `init()` again — infinite loop.

**Move all setup to `.task {}`** on the view that owns the state. `.task` runs once when the view appears, not on every body evaluation.

Bad:
```swift
@Observable class Manager {
    init() { fetchAll() }  // Mutates published state -> re-render loop
}
```

Good:
```swift
@Observable class Manager {
    init() {}  // No side effects
}
// In the view:
.task { manager.fetchAll() }
```

## Testing

- Services are the most testable layer — no UI dependencies
- Keep business logic in services, not in view bodies or model extensions

## @Observable Mutation Safety — View Body

**Never mutate @Observable properties during view body evaluation.**

This includes:
- Direct property writes in computed body or view init
- Calling methods that mutate @Observable state from within body
- Side effects in `onAppear` that trigger synchronous @Observable mutations visible to the current render pass

Mutations must happen from:
- Button action handlers
- `.task {}` blocks (async context, after initial render)
- `onChange(of:)` handlers
- Explicit user interaction callbacks

Violation causes infinite re-render loops (100% CPU, app freeze). SwiftUI re-evaluates the body because state changed, which mutates again, which triggers re-evaluation — infinite loop.

**Real example:** `usedWords.insert(word)` in `GameContainerView.body` caused 100% CPU freeze (Apr 14). Fix: moved mutation to `MainMenu.gameEnded()` (button action handler).
