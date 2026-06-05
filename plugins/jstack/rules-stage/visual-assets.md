---
paths:
  - "Assets/**"
  - "**/GameIcons/**"
  - "**/AppIcon/**"
---

# Visual Asset Creation

## SVG Rendering

ImageMagick (`magick`) cannot reliably render SVG strokes — it drops them silently. Always use `rsvg-convert` for SVG→PNG conversion:

```bash
rsvg-convert -w 512 -h 512 input.svg -o output.png
```

If `rsvg-convert` is not installed: `brew install librsvg`

## Self-Verification (mandatory)

Before showing ANY visual asset to Boss or opening it externally:

1. Convert to PNG using `rsvg-convert`
2. Read the PNG with the Read tool (Claude Code can view images)
3. Check: correct colors? Centered? Correct proportions? No rendering artifacts?
4. Only then present to the user

Never `open` an SVG/PNG for user review without first verifying it yourself. The user's time is more valuable than a render check.

## Icon Design Constraints

When creating game/app icons:
- Use the app's color palette (read from codebase, not guessed)
- No outer padding unless explicitly requested
- Square aspect ratio with matching visual weight across a set
- Transparent background by default
- 512×512 viewBox standard
