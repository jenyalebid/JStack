---
paths:
  - "**/Views/**/*.swift"
  - "**/Screens/**/*.swift"
  - "**/Sheets/**/*.swift"
  - "**/Forms/**/*.swift"
  - "**/Components/**/*.swift"
  - "**/Modifiers/**/*.swift"
  - "**/Styles/**/*.swift"
---

# iOS Design Ethos

How to build iOS apps with consistency, care, and craft. Every app from the same team should feel like it came from the same designer with the same taste — no matter how many engineers, how many features, how many years.

## The 10 principles

1. **Views are pure functions of state.** No imperative refresh hacks. `@Query`/`@FetchRequest` with `animation:` parameters make list changes smooth automatically. Manual `refreshID = UUID()` triggers only for date-rollover edge cases.

2. **State flows through `.environment()`, not props.** App-level state lives in `@Observable` classes injected at the root. Deeply nested views access what they need directly — no prop drilling. Mark every `@Observable` class `@MainActor` (unless the target sets main-actor default isolation): views read the model on the main actor, so an unisolated model lets background writes race those reads — Swift 6 strict concurrency flags exactly this.

3. **Styling is parameterized via environment values, not hardcoded.** Colors, spacing, layout flow through environment + `transformEnvironment()`. New visual variant = add a parameter, don't fork the component.

4. **Composition over configuration — extract a component if a view exceeds ~150 lines.** Small focused views compose into complex screens.

5. **Animations are namespace-driven and choreographed.** `matchedGeometryEffect` with shared namespace IDs for coordinated transitions. Spring `response: 0.6, dampingFraction: 0.8` for natural motion. Things don't just appear/disappear.

6. **Every interaction has feedback.** `.tapScaleEffect()`, `.shakeEffect()`, primary-action button styles with sensory feedback. Silence is a bug.

7. **iOS 26 vs 18 adapts at the modifier/component level, not sprinkled.** `IS_iOS26` / `#available(iOS 26.0, *)` for glass on 26, material+shadow on 18. Don't scatter version checks; adapt at the modifier so views stay clean.

8. **Library-first — rebuild-never.** Before writing any new component / sheet / modifier / share card / share sheet: grep the app codebase AND your shared UI library for existing siblings. If one exists, use or extend it. If stale, propose an update — don't fork a local workaround. **Parallel-surfaces clause:** N mode-specific surfaces means extract the shared chrome (footer, header, band layer, panel) to ONE component reused by all modes BEFORE writing the Nth.

9. **"Shared component" means feature parity, not just chrome unification.** When migrating a mode onto a shared shell, audit the OTHER modes' wired features (timer, intro, share, popovers) and either wire them up for the new mode or explicitly state which are absent and why.

10. **Toolbar slots use `NavigationStack` + `ToolbarItem(placement:)`.** Hand-rolled `HStack` mimicking a toolbar IS the bug. Sheet presentation: "Dismiss X, present Y" is sequential — `pending` flag on host + `dismiss()` + fire Y from `.onDismiss`. Never stack sheets.

## Architecture pattern

```
App Root
  → @Observable state hubs injected via .environment()
  → PresentationController for modal routing (type-safe enum)
  → .presentationController INNERMOST, environments OUTERMOST

Views
  → Model extensions for organization (Model+UI, Model+Computed)
  → Environment for shared state, @State/@Binding for local UI only
  → @Query (SwiftData) or @FetchRequest (CoreData) with animation:

Shared packages (extract once, reuse across every app)
  → UI library: presentation controllers, dismiss buttons, primary-action button styles, flow layouts, progress rings, version-adapt helpers (e.g. an IS_iOS26 boolean)
  → Core library: shared enums (app identity, feature flags), Date/String/Collection extensions, CoreData/SwiftData helpers
  → App-specific modifiers for per-app styling (e.g. `.cardBackground`, `.appBackground`)
```

## Project structure (component-type folders)

```
{App}/
├── App/          Entry, environments, navigation root, Style
├── Models/       @Model entities + extensions, by feature subfolder
├── Enums/        All enum types
├── Protocols/    Protocol definitions
├── Services/     Non-UI logic
├── Screens/      Tab roots + nav destinations (*Screen.swift)
├── Sheets/       Modals (*Sheet.swift), by feature subfolder
├── Forms/        Edit views, pickers, settings (*EditView.swift)
├── Components/   Reusable UI (*View.swift), by feature subfolder
├── Modifiers/    ViewModifiers (*Modifier.swift)
├── Styles/       ButtonStyle/LabelStyle/constants (*Style.swift)
└── Support/      Debug, demo, previews
```

Feature names are subfolders within each type. Max 2 levels deep.

## SwiftUI skill routing

If the SwiftUI skills are installed, they layer — consult the right one instead of loading all three:

- **`swiftui-specialist`** (Apple) — primary for writing/reviewing SwiftUI correctness: dataflow and input narrowing, view structure, ForEach identity, localization, soft-deprecated API lookup.
- **`swiftui-whats-new-27`** (Apple) — mandatory before touching code built against the 27 SDKs. `@State` is a macro there: init-assignment compile errors have a documented fix, and the intuitive one (reordering init assignments) is wrong. Also covers drag-to-reorder, toolbar overflow, swipe-action containers, AsyncImage caching.
- **`swiftui-expert-skill`** — Instruments trace recording/analysis, Liquid Glass adoption, macOS specifics, animation patterns, and iOS 15–26 versioned API history.

These rules carry team conventions; the skills carry framework truth. Where they disagree on framework behavior, the newest Apple skill wins — then update the rule.

## Build is not verify

A successful build tells you nothing about whether the feature works. Always verify visually — run on simulator, walk the user flow, screenshot the result. "The compiler is happy" is the floor, not the ceiling.

## Live iteration: build automatically, NEVER install automatically

During a live session with the user, when they request a code edit: edit → build → report. Don't ask "want me to build?" — the build IS the verification step.

**Install — any install, simulator or hardware — needs explicit per-action authorization, same gate as `git push`.** That includes installing via Xcode, `xcrun simctl install`, or any wrapper script. After a green build, stop and report "built green, ready to install" — wait for the user's go.

Exception: if the user explicitly said "run on sim X" as a standing directive for this loop, install+launch on every rebuild until that loop ends. Don't re-ask each time.

## Git discipline — major-version branches

- One branch per major version. Older versions (`legacy`, `v2.1`, `v3`) are locked — no pushes. The active version branch (e.g. `v4`) is current until release; all next-ship work lands here. At release: merge active → `main`, lock, cut next.
- Task branches cut from the active version branch, not `main`.
- Live session = commit to active version branch directly. No PR ceremony unless asked.
- Don't commit every individual edit during live iteration. One commit at a natural stopping point.
- Never `git push` without explicit per-action authorization. "Commit and push" applies to THAT push only.

## Widget / extension version parity

When you bump `CURRENT_PROJECT_VERSION` or `MARKETING_VERSION` on the parent app target, every widget / live-activity / extension target in the same pbxproj matches in the SAME commit. Parent bump and extension bump are one atomic edit, not two.
