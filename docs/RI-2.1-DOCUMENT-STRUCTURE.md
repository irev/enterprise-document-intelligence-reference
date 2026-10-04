# RI-2.1 — Canonical Document Structure

## Objective

Represent parser/OCR output as evidence-grade structure rather than a single text blob.

## Coordinate system

Bounding boxes use normalized page coordinates:

```text
top-left = (0,0)
bottom-right = (1,1)
bbox = x0,y0,x1,y1
```

The canonical model validates `0 <= x0 <= x1 <= 1` and `0 <= y0 <= y1 <= 1`. Page physical/render dimensions are retained separately.

Normalized coordinates keep evidence independent from parser pixel density while allowing a portal/control panel to map evidence back onto a rendered page.

## Structure

```text
StructuredDocument
  -> PageStructure[]
       -> TextBlock[]
       -> TableBlock[]
            -> TableCell[]
```

Every block has stable identity within the document and explicit reading order. Tables retain row/column position and cell-level coordinates.

## Evidence invariants

- structure is bound to the exact SourceObservation ID and SHA-256;
- page numbering is one-based and contiguous;
- block IDs are unique within the document;
- reading-order positions cannot collide within a page;
- bounding boxes are normalized and ordered;
- parser/layout component and version are mandatory;
- confidence, when present, is bounded to [0,1].

These invariants allow later extraction evidence to reference page/block/region rather than copying untraceable OCR strings.

## Trust

Layout text, table content, coordinates and confidence are model/parser output and remain untrusted data. Structure validation establishes shape and provenance; it does not establish business truth, authenticity or authorization.
