# Performance

The PS3 performance criterion asks for the pipeline to handle scale (the brief
cites 500 requirements + 5,000 evidence records) in under 60 seconds, measured
with the LLM off or cached. OMNIS ships an LLM-off default, so every number here
is the real offline path, and the perf harness now runs that exact 500 + 5,000
scale rather than extrapolating from a smaller set.

## How to reproduce

    make perf
    # or: python -m omnis perf            (defaults: 500 requirements, 5,000 evidence)
    # or: python -m omnis perf --reqs 500 --n 5000

`omnis perf` synthesizes the requirements and evidence in memory, then times the
three scale-sensitive pipeline stages: map evidence to requirements, score
compliance, audit corpus integrity. Synthesis is setup and is timed separately,
not counted. It writes nothing and needs no API key.

## Measured number

Machine: AMD Ryzen 7 7840HS (WSL2 Linux), Python 3.11, single process.

| Stage | Time (500 requirements + 5,000 evidence rows) |
|---|---|
| map | ~0.40s |
| score | ~0.03s |
| integrity | ~0.01s |
| **TOTAL** | **~0.45s (observed 0.43-0.72s across runs)** |

Bar: full pipeline < 60s. Measured well under 1 second at the full target scale,
**PASS**, with about two orders of magnitude of headroom.

## Honest notes on the number

- **Scale shown is the scale asked for.** The run scores 5,000 evidence rows
  against 500 synthesized requirements, the brief's stated production figure. The
  requirements are generated with varied control text so the TF-IDF index has
  real vocabulary, not 500 identical documents.
- **Where the time goes.** The `map` stage dominates, because rows whose id is
  missing or orphaned fall through to the TF-IDF layer, which is O(rows x
  requirements): cosine over 500 requirements for those rows. Rows with a known
  id resolve on the exact-id layer (a dict lookup). Even with the TF-IDF fallback
  doing real work at 500 requirements, the total stays under a second.
- **Run-to-run variance.** The number moves a little between runs (0.43-0.72s
  observed) with system load; all are far inside the 60s bar.
- **No LLM in the timed path.** The LLM adapter is off by default and is not
  called during the pipeline. The numbers above are the shipped offline path,
  not a cached-LLM best case.
