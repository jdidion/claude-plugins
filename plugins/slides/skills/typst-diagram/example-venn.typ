#set page(width: 28cm, height: 12cm, margin: 0.4cm, fill: white)
#set text(font: ("Helvetica Neue", "Helvetica", "Inter", "Arial", "DejaVu Sans"), size: 14pt)

#let natera-teal = rgb("#00788a")
#let google     = rgb("#fef08a")
#let openai     = rgb("#bbf7d0")
#let anthropic  = rgb("#a5f3fc")
#let gray-bg    = rgb("#e5e7eb")

// Triadic zone palette: orange (30°) → green (150°) → violet (270°), 120° apart.
// Maximum sequential contrast; no two adjacent hues within 60° on the color wheel.
#let zone-research-fill = rgb("#fed7aa")  // peach/orange
#let zone-automate-fill = rgb("#d1fae5")  // mint green
#let zone-build-fill    = rgb("#ddd6fe")  // violet
#let zone-research-stroke = rgb("#ea580c")
#let zone-automate-stroke = rgb("#16a34a")
#let zone-build-stroke    = rgb("#7c3aed")

#let surface-card(title, card-width: 5cm, ..items) = box(
  width: card-width,
  stroke: 2pt + natera-teal,
  radius: 6pt,
  fill: white,
  inset: 10pt,
)[
  #set align(center)
  #text(weight: "bold", size: 15pt, fill: natera-teal)[#title]
  #v(6pt)
  #stack(dir: ttb, spacing: 7pt, ..items.pos())
]

#let chip(label, fill: gray-bg, stroke-color: rgb("#6b7280"), txt-color: black, italic: false, bold: false) = box(
  fill: fill,
  stroke: 0.8pt + stroke-color,
  radius: 4pt,
  inset: (x: 12pt, y: 8pt),
)[#text(size: 14pt, fill: txt-color, style: if italic { "italic" } else { "normal" }, weight: if bold { "bold" } else { "regular" })[#label]]

// Layout: 28cm wide, 0.4cm margins → 27.2cm usable.
// Every card has UNIFORM 0.5cm gap to its nearest zone stroke on all sides.
// A-only = 0 so Research-right-stroke and Build-left-stroke coincide at x=12cm (one visible line).
// R-only 5.5cm (Web chat 4.5cm), R∩A 6.5cm (Desktop 5.5cm), A∩B 6.5cm (CLI 5.5cm), B-only 8.7cm (IDE 7.7cm).
// Total: 5.5 + 6.5 + 0 + 6.5 + 8.7 = 27.2cm ✓
// Research [0, 12]    → R-only [0, 5.5], R∩A [5.5, 12]
// Automate [5.5, 18.5] → R∩A, A-only [12, 12] (0cm), A∩B [12, 18.5]
// Build    [12, 27.2]  → A∩B, B-only [18.5, 27.2]
#let zone-y = 1.1cm
#let zone-h = 10.5cm
#let research-x = 0cm
#let research-w = 12cm
#let automate-x = 5.5cm
#let automate-w = 13cm
#let build-x = 12cm
#let build-w = 15.2cm

#box(width: 100%, height: 100%)[
  // Three overlapping zones (background)
  #place(top + left, dx: research-x, dy: zone-y,
    rect(width: research-w, height: zone-h,
         fill: zone-research-fill,
         stroke: 2pt + zone-research-stroke,
         radius: 28pt))
  #place(top + left, dx: automate-x, dy: zone-y,
    rect(width: automate-w, height: zone-h,
         fill: zone-automate-fill.transparentize(40%),
         stroke: 2pt + zone-automate-stroke,
         radius: 28pt))
  #place(top + left, dx: build-x, dy: zone-y,
    rect(width: build-w, height: zone-h,
         fill: zone-build-fill.transparentize(40%),
         stroke: 2pt + zone-build-stroke,
         radius: 28pt))

  // Zone labels — A-only is 0cm so place Automate label between Desktop and CLI at x=12cm.
  // R-only center: 2.75cm, A-only center: 12cm, B-only center: 22.85cm
  #place(top + left, dx: 2.75cm - 1.6cm, dy: 0.3cm,
    text(weight: "bold", size: 18pt, fill: zone-research-stroke)[Research])
  #place(top + left, dx: 12cm - 1.8cm, dy: 0.3cm,
    text(weight: "bold", size: 18pt, fill: zone-automate-stroke)[Automate])
  #place(top + left, dx: 22.85cm - 1.1cm, dy: 0.3cm,
    text(weight: "bold", size: 18pt, fill: zone-build-stroke)[Build])

  // Compute overlap centers
  // Research-only: [research-x, automate-x] → center at (research-x + automate-x) / 2
  // R∩A: [automate-x, research-x + research-w] → center at midpoint
  // A∩B: [build-x, automate-x + automate-w] → center at midpoint
  // Build-only: [automate-x + automate-w, build-x + build-w] → center at midpoint

  #let slot(cx, width, body) = place(top + left, dx: cx - width/2, dy: zone-y,
    box(width: width, height: zone-h)[
      #set align(center + horizon)
      #body
    ])

  // Web chat — center of R-only [0, 6.1] = 3.05cm, card 4.5cm
  #slot((research-x + automate-x) / 2, 5.5cm, surface-card([Web chat], card-width: 4.5cm,
    chip([Gemini], fill: google, stroke-color: rgb("#ca8a04")),
    chip([ChatGPT], fill: openai, stroke-color: rgb("#15803d")),
    chip([Synapse], fill: natera-teal, stroke-color: rgb("#003d47"), txt-color: white, bold: true),
  ))

  // Desktop — center of R∩A [6.1, 12.1] = 9.1cm, card 5.5cm
  #slot((automate-x + research-x + research-w) / 2, 6cm, surface-card([Desktop], card-width: 5.5cm,
    chip([CoWork (Bedrock)], fill: anthropic, stroke-color: rgb("#0e7490")),
    chip([Gemini desktop], fill: google, stroke-color: rgb("#ca8a04")),
  ))

  // CLI — center of A∩B [12.6, 18.6] = 15.6cm, card 5.5cm
  #slot((build-x + automate-x + automate-w) / 2, 6cm, surface-card([CLI], card-width: 5.5cm,
    chip([Claude Code (Bedrock)], fill: anthropic, stroke-color: rgb("#0e7490")),
    chip([more coming], fill: gray-bg, stroke-color: rgb("#6b7280"), italic: true),
  ))

  // IDE + Local — center of B-only [18.5, 27.2] = 22.85cm, cards 7.7cm wide
  #slot((automate-x + automate-w + build-x + build-w) / 2, 8.2cm,
    stack(dir: ttb, spacing: 14pt,
      surface-card([IDE], card-width: 7.7cm,
        chip([Cursor], fill: openai, stroke-color: rgb("#15803d")),
        chip([Claude Code (VS Code / Cursor)], fill: anthropic, stroke-color: rgb("#0e7490")),
      ),
      surface-card([Local], card-width: 7.7cm,
        chip([subagents only (out of scope today)], fill: gray-bg, stroke-color: rgb("#6b7280"), italic: true),
      ),
    ))
]
