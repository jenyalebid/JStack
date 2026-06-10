---
paths:
  - "**/Lists/**"
  - "**/*List.swift"
  - "**/*ListView.swift"
  - "**/*Grid.swift"
  - "**/*GridView.swift"
  - "**/*Collection.swift"
---

# Lists & Collections

Rules for views that display collections of items — scrollable lists, grids, and grouped collections.

## When to Use What

| Pattern | When |
|---------|------|
| `List` | System-styled rows with built-in separators, swipe actions, sections. Settings, simple data lists |
| `LazyVStack` in `ScrollView` | Custom row layouts, mixed content types, cards. Most app content |
| `LazyVGrid` | Grid layouts — book covers, image galleries, icon grids |
| `ForEach` in `VStack` | Small fixed collections (< 10 items) that don't need lazy loading |

## List Rows

A row should communicate its content at a glance:

- **Primary info** on the left (title, image)
- **Secondary info** below or trailing (subtitle, metadata)
- **Action indicator** trailing (chevron for navigation, toggle for settings)
- Consistent row height within a section — don't mix tall and short rows

Rows that navigate should use `NavigationLink` or have a clear visual affordance (chevron).

## Sections

- Use section headers to group related items. Keep headers short (1-3 words)
- `Section("Header") { }` for system List
- Custom `HeaderLabel` or similar for ScrollView-based lists
- Visual separation between sections: spacing (16pt+) or dividers, not both

## Empty State

**Never show a blank list.** When data is empty:

```swift
if items.isEmpty {
    ContentUnavailableView(
        "No Books",
        systemImage: "books.vertical",
        description: Text("Books you add will appear here")
    )
} else {
    // list content
}
```

Include an action when the user can fix the empty state ("Add Book", "Start Search").

## Swipe Actions

- **Leading swipe** — primary/positive action (pin, favorite, mark read)
- **Trailing swipe** — destructive/secondary action (delete, archive)
- Use `.tint()` to color swipe actions (`.red` for destructive, accent for positive)
- Destructive swipes should use `.role(.destructive)` for the red background
- Below the 27 SDKs, `.swipeActions {}` only works on `List` rows. On SDK 27+, rows inside a `ScrollView` (`LazyVStack`, `LazyVGrid`, plain stacks) take the same row modifier once the scrollable container gets `.swipeActionsContainer()` (iOS 27+, gate it). Without the container modifier, row swipe actions outside `List` silently do nothing — don't hand-roll gesture-based swipe rows to work around that on 27

## Loading

- Show skeleton/shimmer rows matching the expected layout while loading
- `LazyVStack` items load on scroll automatically — no special handling needed
- For paginated content, show a loading indicator at the bottom and load more on scroll
- `AsyncImage` in rows/grids: on the 2027 OS releases it HTTP-caches by default (honors server cache headers, even in apps built against older SDKs) — "images reload on scroll-back" is no longer a reason to hand-roll a cache. For explicit control: `AsyncImage(request:)` with a `URLRequest` cache policy, or `asyncImageURLSession(_:)` for a custom `URLCache` — both iOS 27+, gate them

## Search & Filter

- `.searchable()` for text search over list content
- Filter chips or segmented control above the list for category filtering
- Filtered empty state should say why it's empty ("No results for 'fantasy'") and offer to clear filters

## Grid Specifics

```swift
LazyVGrid(columns: columns, spacing: 12) {
    ForEach(items) { item in
        ItemCard(item: item)
    }
}
```

- Use `GridItem(.adaptive(minimum: N))` for flexible column counts that adapt to screen width
- Consistent aspect ratios within a grid
- Grid spacing: 8-12pt between items

## Verification

When reviewing a list or collection:
- Empty state exists and is helpful (not just "No data")
- Rows have consistent height and alignment within sections
- Swipe actions work and use appropriate colors/roles
- Scrolls smoothly with large data sets (use Lazy containers)
- Grid adapts to different screen widths

## CoreData @FetchRequest

`@FetchRequest` wraps `NSFetchedResultsController`. These rules are non-negotiable:

### Sort Descriptors Required
Every `@FetchRequest` **must** have at least one sort descriptor. `NSFetchedResultsController` crashes without them — no exceptions.

```swift
// CORRECT
@FetchRequest(
    sortDescriptors: [SortDescriptor(\Entry.createdAt, order: .reverse)]
) private var results: FetchedResults<Entry>

// WRONG — crashes at runtime
@FetchRequest(sortDescriptors: []) private var results: FetchedResults<Entry>
```

### Entity Resolution
Never use the explicit `entity:` parameter. Let SwiftUI infer the entity from the generic type:

```swift
// CORRECT — entity resolved lazily from generic type + managed object context
@FetchRequest(sortDescriptors: [...]) private var results: FetchedResults<Entry>

// WRONG — resolves entity eagerly before context is available, crashes
@FetchRequest(entity: Entry.entity(), sortDescriptors: [...])
```

### For Explicit Fetch Requests
When you need predicates or custom configuration, use the `fetchRequest:` init with a typed request:

```swift
let request: NSFetchRequest<Entry> = Entry.fetchRequest()
request.sortDescriptors = [NSSortDescriptor(keyPath: \Entry.createdAt, ascending: false)]
request.predicate = NSPredicate(format: "isArchived == NO")

@FetchRequest(fetchRequest: request) private var activeEntries: FetchedResults<Entry>
```
