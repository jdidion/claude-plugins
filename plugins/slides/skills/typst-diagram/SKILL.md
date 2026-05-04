---
name: typst-diagram
description: Author publication-quality diagrams (Venn layouts, flow charts, grouped-card figures, network diagrams) as Typst source and compile to PNG/SVG for slide decks and papers. Use when the user asks for a pixel-accurate or typographically polished figure — especially multi-zone Venn layouts, grouped-card rosters, or anything that needs precise geometric control. For quick/informal sketches with overlapping shapes, prefer the sibling `drawio` skill.
---

# /typst-diagram — Author diagrams in Typst

Typst is an excellent choice for diagrams destined for slide decks and papers: crisp vector output, precise geometric control, declarative composition, and fast re-compile. This skill captures a battle-tested authoring recipe so new diagrams don't re-invent the layout math from scratch.

**See also:** the sibling `drawio` skill in this plugin — lighter-weight, WYSIWYG-friendly XML, great for informal sketches and quick overlapping-shape diagrams. Use Typst when typography, alignment math, and re-compile iteration matter; use draw.io when you need a fast result or plan to hand-edit later.

## When to use

- User asks for a diagram that will live in a slide deck, report, or paper.
- The diagram has multiple named regions (Venn, tiers, categories, pipeline stages).
- The user wants iterative refinement with pixel-accurate control.

**Skip if:** the diagram is a one-off sketch, an informal notebook illustration, or requires hand-drawn aesthetics. For those, Mermaid or draw.io is faster.

## Output location

Diagrams live as standalone `.typ` files alongside the consuming document:

```
project/
├── diagrams/
│   ├── my-diagram.typ
│   └── my-diagram.png   # compiled output, checked in
├── slides/
│   └── deck.typ         # imports the PNG via #image("../diagrams/my-diagram.png")
```

Compile pattern (supports `../` in `image()`):
```bash
typst compile --root <project-root> diagrams/my-diagram.typ diagrams/my-diagram.png --format png --ppi 220
```

`ppi: 220` is the sweet spot for 28cm-wide figures targeting 16:9 slides — high enough for detail, low enough for PPTX embed size.

## Core authoring recipe

### 1. Set an explicit page size

Diagrams are typically embedded at a fixed size, so set the page accordingly:
```typst
#set page(width: 28cm, height: 12cm, margin: 0.4cm, fill: white)
#set text(font: ("Helvetica Neue", "Helvetica", "Inter", "Arial", "DejaVu Sans"), size: 14pt)
```

Use sans-serif for slide-destined diagrams — serifs read poorly at projection distance. The stack above degrades gracefully: macOS picks Helvetica Neue, Linux CI falls through to Inter / Arial / DejaVu Sans. Typst silently substitutes if the first few are missing, so keep at least one portable fallback.

### 2. Define reusable cards and chips

```typst
#let surface-card(title, card-width: 5cm, ..items) = box(
  width: card-width,
  stroke: 2pt + rgb("#00788a"),
  radius: 6pt,
  fill: white,
  inset: 10pt,
)[
  #set align(center)
  #text(weight: "bold", size: 15pt, fill: rgb("#00788a"))[#title]
  #v(6pt)
  #stack(dir: ttb, spacing: 7pt, ..items.pos())
]

#let chip(label, fill: rgb("#e5e7eb"), stroke-color: rgb("#6b7280"), ...) = box(
  fill: fill,
  stroke: 0.8pt + stroke-color,
  radius: 4pt,
  inset: (x: 12pt, y: 8pt),
)[#text(size: 14pt, ...)[#label]]
```

### 3. Lay out zones and slots with explicit math

For multi-region layouts (e.g., a 3-zone Venn), compute geometry backwards from card widths + a **uniform gap constant**:

- Pick a gap (e.g., 0.5cm) that every card will have on all sides.
- Each zone's non-overlap region width = card-width + 2 × gap.
- Each overlap region width = card-width + 2 × gap.
- Total = sum of all regions. Adjust one slack region to make total = canvas width.

```typst
// Example: 3-zone Venn, cards 4.5cm-5.5cm wide, 0.5cm uniform gap, 27.2cm canvas
#let research-x = 0cm
#let research-w = 12cm           // R-only 5.5 + R∩A 6.5 = 12cm
#let automate-x = 5.5cm
#let automate-w = 13cm            // R∩A + A-only 0 + A∩B 6.5 = 13cm
#let build-x = 12cm
#let build-w = 15.2cm             // A∩B + B-only 8.7 = 15.2cm
```

The A-only strip can collapse to 0 so bordering strokes coincide into a single visual divider — better than leaving accidental pale space.

### 4. Triadic color palette for 3-zone sequences

Use hues 120° apart on the HSL wheel. Battle-tested palette:
- Orange: `#fed7aa` fill / `#ea580c` stroke (H≈30°)
- Green:  `#d1fae5` fill / `#16a34a` stroke (H≈150°)
- Violet: `#ddd6fe` fill / `#7c3aed` stroke (H≈270°)

Fill lightness ≥90% keeps black text readable. Avoid three pastels in the same family (e.g., violet+pink+blue) — adjacent hues blur.

### 5. Position cards in slots

```typst
#let slot(cx, width, body) = place(top + left, dx: cx - width/2, dy: zone-y,
  box(width: width, height: zone-h)[
    #set align(center + horizon)
    #body
  ])

#slot(3cm, 5.5cm, surface-card([Label], card-width: 4.5cm,
  chip([one]),
  chip([two]),
))
```

## Review loop

Render and verify every iteration:

```bash
typst compile --root <root> diagrams/my.typ diagrams/my.png --format png --ppi 220
```

**Do NOT** trust the `Read` tool for the rendered PNG — it caches images and returns stale content. Instead:

1. **Pixel sample via Python+Pillow** for correctness checks (colors, widths, wraps):
   ```python
   from PIL import Image
   img = Image.open('diagrams/my.png')
   print(img.getpixel((x, y)))  # fill at coord
   ```
2. **Visually inspect via cmux browser** (cache-bust via query string):
   ```bash
   cmux new-surface --type browser --url "file://$PWD/diagrams/my.png?v=$(date +%s%N)"
   ```

## Common pitfalls

- **Text wraps in a chip:** chip's parent stack is narrower than text natural width. Widen the card's `width:` and retest.
- **Card widths look uneven across a row:** cards with `width: auto` size to content. Set explicit `width:` to fix.
- **Zone fill doesn't fill the canvas where expected:** check that `place()` offsets align with region boundaries; zone sampling often surprises.
- **`image("../x.png")` fails to compile:** pass `--root <parent-dir>` to the typst command.

## See also

- `patterns.md` in the `figure-review` skill (parent workspace) — accumulated defect classes and positive patterns from figure-review iterations.

---

## Example: 3-zone Venn with grouped cards

See `example-venn.typ` in this skill's directory for a complete, compile-ready example that implements all the rules above (triadic palette, uniform gaps, collapsed middle strip, reusable card/chip helpers).
