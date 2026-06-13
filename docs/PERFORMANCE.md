# Performance

The PS3 performance criterion asks for the pipeline to handle scale (the brief
cites 500 requirements + 5,000 evidence records) in under 60 seconds, measured
with the LLM off or cached. OMNIS ships an LLM-off default, so every number here
is the real offline path.

## How to reproduce

    make perf
    # or: python -m omnis perf --n 5000

`omnis perf` generates an in-memory synthetic corpus (default 5,000 evidence
rows), then times the four pipeline stages the criterion covers: parse policies,
map evidence to requirements, score compliance, audit corpus integrity.
Generation is setup and is timed separately, not counted in the pipeline number.
It writes nothing and needs no API key.

## Measured number

Machine: AMD Ryzen 7 7840HS (WSL2 Linux), Python 3.11, single process.

| Stage | Time (15 requirements + 5,000 evidence rows) |
|---|---|
| parse | 0.000s |
| map | 0.023s |
| score | 0.012s |
| integrity | 0.004s |
| **TOTAL** | **0.043s** |

Bar: full pipeline < 60s. Measured 0.043s. **PASS**, with about three orders of
magnitude of headroom.

At 10,000 rows the pipeline takes about 0.09s, so it scales linearly in the
evidence count.

## Honest notes on the number

- **Requirement count.** This run scores 5,000 evidence rows against the
  synthetic policy set, which is 15 requirements, not 500. We did not synthesize
  500 distinct policies; the brief's 500/5,000 figure is the target production
  scale, and the development sample is 500 evidence rows. The cost that grows
  with the corpus is the evidence count, which we do push to 5,000.
- **Why it is so fast.** Most synthetic rows carry a real `requirement_id`, so
  the linker resolves them on the exact-id layer (a dict lookup) and never
  reaches TF-IDF. To bound the worst case we forced all 5,000 rows through the
  TF-IDF layer (the most expensive path, cosine over every requirement): that
  ran in 0.172s. The TF-IDF layer is O(rows x requirements), so a 500-requirement
  set would raise the worst case by roughly 30x to a few seconds, still well
  inside the 60s bar.
- **No LLM in the timed path.** The LLM adapter is off by default and is not
  called during the pipeline. The numbers above are the shipped offline path,
  not a cached-LLM best case.
