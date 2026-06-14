# Fonts

The report PDF is typeset in **Latin Modern Roman** (the OpenType form of Computer
Modern, the classic LaTeX typeface), so the generated report reads like a paper.

- `lmroman10-regular.otf`, `lmroman10-bold.otf`, `lmroman10-italic.otf`
- Source: the Latin Modern project (GUST e-foundry), via CTAN.
- License: GUST Font License (GFL), see `LICENSE-LatinModern.txt`. The GFL permits
  redistribution, so the fonts ship in the repo and the report renders offline with
  no system font install.

`omnis/report/builder.py` embeds and subsets these at render time (via fpdf2, which
already depends on fonttools). If the files are missing, the renderer falls back to
the core Times font so the engine never breaks.
