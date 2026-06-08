---
paths:
  - "**/Charts/**"
  - "**/*Chart.swift"
  - "**/*Chart*.swift"
  - "**/*Stats*.swift"
---

# Charts & Data Visualization

Rules for views that visualize data — charts, progress indicators, and stat displays. Uses Swift Charts framework.

## When to Use a Chart

- Showing trends over time (reading minutes per day, weekly progress)
- Comparing values across categories (pages by genre, scores by mode)
- Showing distribution or composition (time breakdown, category split)

**Not a chart:** Single values (use a stat label), binary state (use a toggle/badge), simple counts (use a number with context).

## Chart Types

| Mark | Use For | Example |
|------|---------|---------|
| `BarMark` | Comparing discrete categories or time periods | Daily reading minutes, books per month |
| `LineMark` | Trends over continuous time | Reading streak, page count growth |
| `AreaMark` | Volume trends with emphasis on magnitude | Cumulative pages read |
| `PointMark` | Individual data points, scatter plots | Session durations |
| `RuleMark` | Reference lines, thresholds, goals | Daily goal line |

Combine marks when useful — `LineMark` + `PointMark` for trend with data points, `BarMark` + `RuleMark` for bars with a goal line.

## Structure

```swift
Chart(data) { item in
    BarMark(
        x: .value("Day", item.date, unit: .day),
        y: .value("Minutes", item.minutes)
    )
    .foregroundStyle(Color.accentColor)
}
.chartYAxis {
    AxisMarks(position: .leading)
}
.frame(height: 200)
```

**Required:**
- Explicit `frame(height:)` — charts don't have intrinsic height. Common values: 150-250pt
- Axis labels that clarify what's being shown
- Foreground style that's meaningful (accent for primary data, semantic colors for categories)

## Style Guidelines

- **One story per chart.** Don't overload. If you need to show two different metrics, use two charts
- **Y-axis on leading side** (`.chartYAxis { AxisMarks(position: .leading) }`) for left-to-right reading
- **Minimal axis labels** — show enough to read the scale, not every value. Let Swift Charts auto-format
- **Color coding** — if multiple series, use distinct colors. Use `.foregroundStyle(by: .value("Category", item.category))` with a meaningful color mapping
- **Goal/reference lines** — use `RuleMark` with `.annotation` for context:
  ```swift
  RuleMark(y: .value("Goal", dailyGoal))
      .foregroundStyle(.secondary)
      .lineStyle(StrokeStyle(dash: [5, 5]))
  ```

## Empty Data

When there's no data to chart:
- Show the chart frame with a message overlaid, not a completely different layout
- "Start reading to see your stats" with a relevant icon
- Keep the visual weight consistent — an empty chart area shouldn't cause layout shift

## Stat Displays

For single-value stats alongside or instead of charts:

```swift
VStack(alignment: .leading, spacing: 4) {
    Text("Pages This Week")
        .font(.caption)
        .foregroundStyle(.secondary)
    Text("\(pageCount)")
        .font(.title.bold().monospacedDigit())
}
```

- Label above or below the value
- `.monospacedDigit()` on numeric values
- Group related stats in horizontal rows

## Accessibility

Swift Charts provides VoiceOver support automatically (Audio Graphs). Enhance with:
- `.accessibilityLabel()` on chart for summary ("Bar chart showing daily reading time for the past week")
- Provide a text alternative for complex visualizations

## Verification

When reviewing a chart or stat view:
- Chart has explicit height and doesn't collapse or overflow
- Axis labels are readable and not overlapping
- Colors are distinguishable (including for colorblind users)
- Empty data state shows a helpful message, not a blank space
- Numeric values use `.monospacedDigit()` to prevent layout jitter
