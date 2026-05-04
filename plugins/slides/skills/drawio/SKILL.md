---
name: drawio
description: Author diagrams as draw.io XML and headlessly export to PNG/SVG/PDF for embedding in slide decks or documents. Use when the user asks for overlapping-shape diagrams (Venn, set logic, region intersections), informal block/flow sketches, or any diagram that benefits from draw.io's large shape library and WYSIWYG-friendly XML. Full loop: Claude writes the XML, renders it, reads the PNG, critiques via figure-review, and iterates.
---

# /drawio — Author diagrams in draw.io XML

Draw.io (diagrams.net) gives you arbitrary-position shapes with fill opacity, rounded rectangles, arrows, and a huge shape library — plus a headless CLI that exports PNG/SVG/PDF with no GUI. It's the fastest path for diagrams that need **overlapping shapes** (Venn, set intersections), or informal block layouts where Typst would be overkill.

## When to use

- User asks for a **Venn diagram** or any figure with **overlapping translucent shapes** (d2 and Mermaid do not support this; Typst works but is heavier).
- User asks for an **informal block / flow sketch** where pixel-perfect control matters less than a quick, editable result.
- The figure will be further edited in the draw.io GUI later (the `.drawio` file is the source of truth — round-trips cleanly).

**Skip if:**
- The diagram is a dense structured diagram (class diagram, ERD, sequence) — Mermaid is faster.
- The diagram needs precise typographic / paper-quality layout — use `typst-diagram`.
- The diagram is a slide itself — use MARP via the parent `/slides` skill.

## Requirements

- `drawio` CLI (macOS: `brew install --cask drawio`).
- Verify: `drawio --version` (should print a version like `29.x`).

## Output location

Diagrams live as standalone `.drawio` files alongside the consuming document, with the rendered PNG checked in beside them:

```
project/
├── diagrams/
│   ├── my-diagram.drawio      # source (XML)
│   └── my-diagram.png         # rendered output
├── slides/
│   └── deck.md                # embeds via ![w:600](../diagrams/my-diagram.png)
```

Both files are text-friendly and git-friendly.

## Core authoring recipe

### 1. Minimal `.drawio` skeleton

```xml
<mxfile host="app.diagrams.net">
  <diagram name="<label>" id="<id>">
    <mxGraphModel dx="800" dy="600" grid="0" gridSize="10" guides="1"
                  tooltips="1" connect="1" arrows="1" fold="1" page="1"
                  pageScale="1" pageWidth="850" pageHeight="600"
                  math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- shape cells go here, parent="1" -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Every shape is an `mxCell` with `vertex="1" parent="1"` and a nested `mxGeometry` giving absolute `x,y,width,height`.

### 2. Shapes and the `style` attribute

The `style` attribute is a semicolon-delimited list of key=value pairs. Key properties:

| key | effect |
|-----|--------|
| `ellipse` / `rounded=1` | shape type (no value for `ellipse`) |
| `fillColor=#RRGGBB` | fill |
| `fillOpacity=50` | translucency (percent, 0–100) — critical for Venn |
| `strokeColor=#RRGGBB` | border |
| `strokeWidth=2` | border thickness |
| `fontSize=24`, `fontColor=#...`, `fontStyle=1` | text (1=bold, 2=italic, 4=underline, combine by adding) |
| `whiteSpace=wrap;html=1` | wrap long labels |
| `align=center;verticalAlign=middle` | text position |

The cell's `value="..."` is the label (HTML-escaped).

### 3. Venn diagram — the canonical overlap case

Three equal circles, centers forming an equilateral triangle. For radius `r`, the center-to-center distance for ~⅓ overlap is `r`. Example (radius 130, canvas 850×600):

```xml
<mxCell id="A" value="A"
        style="ellipse;whiteSpace=wrap;html=1;fillColor=#FF6B6B;fillOpacity=50;strokeColor=#C0392B;fontSize=24;fontStyle=1;"
        vertex="1" parent="1">
  <mxGeometry x="120" y="140" width="260" height="260" as="geometry"/>
</mxCell>
<mxCell id="B" value="B"
        style="ellipse;whiteSpace=wrap;html=1;fillColor=#4ECDC4;fillOpacity=50;strokeColor=#16A085;fontSize=24;fontStyle=1;"
        vertex="1" parent="1">
  <mxGeometry x="320" y="140" width="260" height="260" as="geometry"/>
</mxCell>
<mxCell id="C" value="C"
        style="ellipse;whiteSpace=wrap;html=1;fillColor=#FFD93D;fillOpacity=50;strokeColor=#B7950B;fontSize=24;fontStyle=1;"
        vertex="1" parent="1">
  <mxGeometry x="220" y="290" width="260" height="260" as="geometry"/>
</mxCell>
```

See `examples/venn-3.drawio` in this skill's directory for a compile-ready copy.

**Fill palette that works well at 50% opacity:**
- Coral `#FF6B6B` / stroke `#C0392B`
- Teal  `#4ECDC4` / stroke `#16A085`
- Gold  `#FFD93D` / stroke `#B7950B`

These are light enough that overlapping regions produce distinct mixed hues without muddying to grey.

### 4. Labels inside intersection regions

Place a separate un-filled text cell at the intersection centroid:

```xml
<mxCell id="ABC" value="A∩B∩C"
        style="text;html=1;align=center;verticalAlign=middle;fontSize=14;fontStyle=1;"
        vertex="1" parent="1">
  <mxGeometry x="290" y="310" width="80" height="30" as="geometry"/>
</mxCell>
```

The default circle `value` renders at the circle center, which collides with intersection labels — either leave circle labels blank and use explicit text cells, or position circle labels near the outer edge by adding `verticalAlign=top;` to their style.

### 5. Arrows / edges

```xml
<mxCell id="e1" style="endArrow=classic;html=1;"
        edge="1" parent="1" source="A" target="B">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

`source`/`target` reference shape IDs; draw.io auto-routes.

## Render loop

```bash
drawio --export --format png --output diagrams/my.png diagrams/my.drawio
# optional: --scale 2 for higher DPI, --transparent for transparent background
```

Supported formats: `png`, `svg`, `pdf`, `jpg`, `xml` (roundtrip).

### Visual verification (full loop)

Draw.io output is deterministic, so you can close the loop without human intervention:

1. **Render.** Run the `drawio --export` command above.
2. **Read** the PNG via the `Read` tool for a first-pass glance. **Caveat:** the Read cache can return stale images for the same path across consecutive renders — if a re-rendered file looks unchanged, read it a second time or open via cmux browser:
   ```bash
   cmux new-surface --type browser --url "file://$PWD/diagrams/my.png?v=$(date +%s%N)"
   ```
3. **Pixel-sample** for ground truth when colors or geometry matter:
   ```python
   from PIL import Image
   img = Image.open('diagrams/my.png')
   print(img.getpixel((x, y)))  # RGBA at coord
   ```
4. **Critique** via the `figure-review` skill — score on alignment, whitespace, hierarchy, color, typography, text-fit, overflow, craft.
5. **Edit the XML** and go back to step 1.

The `figure-review` skill has the full rubric and failure modes — use it. Don't claim "done" on a figure without running it at least once.

## Common pitfalls

- **Circles appear solid, not translucent.** You set `fillColor` but forgot `fillOpacity=50`. Default is 100.
- **Label disappears behind an overlap.** Draw order is document order — shapes declared later draw on top. Put labels after circles, or use separate text cells.
- **`drawio --export` hangs.** First invocation may open the Electron UI briefly; subsequent calls use cached process. If it hangs > 10s, kill it and retry; the macOS Electron binary sometimes needs a `open -a draw.io` warm-up.
- **PNG is clipped.** `pageWidth`/`pageHeight` in `mxGraphModel` define the export viewport. Shapes outside that rectangle are cropped. Either grow the page or move the shapes.
- **SVG looks fine but PNG is fuzzy.** PNG export uses on-screen DPI by default. Pass `--scale 2` (or higher) for crisp slide-quality output.

## Quick reference

```bash
# Render once
drawio --export --format png --output out.png in.drawio

# Render at 2× scale, transparent background
drawio --export --format png --scale 2 --transparent --output out.png in.drawio

# Render to SVG (for vector-quality embedding)
drawio --export --format svg --output out.svg in.drawio

# Open for manual edit
open -a draw.io in.drawio
```

## See also

- Sibling `typst-diagram` skill in this plugin — heavier, but pixel-perfect and better for publication-quality figures (multi-zone Venn with uniform gaps, triadic palette, reusable card/chip helpers).
- `figure-review` (user-local skill) — aesthetic rubric; run after every render.
- Parent `slides` skill — embed the rendered PNG in MARP decks via `![w:600](../diagrams/my.png)`.
