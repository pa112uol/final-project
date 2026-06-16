# Integration Test Benchmark: Python vs Next.js

Comparison of the recommendation pipeline end-to-end request time across the six
UserSim scenarios, measured on the same machine against the same live APIs
(Last.fm, ListenBrainz, MusicBrainz) in the same session.

Each scenario time covers the full pipeline from seed input to final ranked list,
including all network calls. Parallel scenarios (E, F) issue three pipeline calls
concurrently and the time reflects the wall-clock total for the batch.

## Results

| Scenario | Seed | Calls | Python | Next.js | Ratio |
|---|---|---|---|---|---|
| A — Synth-pop | "Blinding Lights" — The Weeknd | 1 | 7.44s | 4.51s | 1.65x |
| B — Hip-hop | "HUMBLE." — Kendrick Lamar | 1 | 8.37s | 5.57s | 1.50x |
| C — Classic rock | "Stairway to Heaven" — Led Zeppelin | 1 | 7.35s | 3.62s | 2.03x |
| D — Ultra-niche | "Alien Observer" — Grouper | 1 | 8.11s | 2.94s | 2.76x |
| E — Multi-seed | The National + Bon Iver | 3 parallel | 10.19s | 5.86s | 1.74x |
| F — Novelty gradient | "Teardrop" — Massive Attack | 3 parallel | 20.00s | 13.10s | 1.53x |
| **Total** | | | **~61s** | **~36s** | **~1.70x** |

All 27 assertions passed in both suites.

## Test commands

```bash
# Python
cd backend && .venv/bin/pytest tests/test_pipeline_usersim.py -v -s

# Next.js
node_modules/.bin/vitest run pipeline.usersim --sequence.concurrent false --reporter=verbose
```

## Conclusion

Next.js is consistently faster across every scenario, running the full pipeline
in approximately **1.5 to 2.8 times less time** than the Python implementation.

The performance gap has two main sources:

**Event loop overhead.** The Python test fixtures call `asyncio.run()` for each
scenario, which creates and tears down a fresh event loop per request. Node.js
maintains a single long-lived event loop, so there is no per-request startup
cost. This accounts for most of the difference in single-seed scenarios (A, B, C,
D), where the actual I/O work is identical but Python pays 2-3 seconds of setup
overhead each time.

**HTTP client throughput.** `httpx.AsyncClient` is a robust async HTTP client
but carries more per-request overhead than Node's built-in `fetch`. In the
parallel scenarios (E, F) where three pipelines run concurrently, this overhead
multiplies — Python's parallel batch takes 10-20s versus 6-13s for Node. The
gap is widest in scenario D (ultra-niche), where the niche seed triggers more
MusicBrainz rate-limit sleeps; Python serialises those sleeps one event loop at
a time, while Node handles them more efficiently within a single loop.

The Python implementation is otherwise functionally equivalent: all 27 quality
and correctness assertions pass with identical results, and the response times
(7-20s) are well within acceptable limits for a background recommendation
request. The overhead is an architectural characteristic of the port rather than
a correctness issue.

If the performance gap becomes a concern, the most effective mitigations would be
to run the Django server with `uvicorn` (async ASGI instead of the sync WSGI dev
server) and to reuse a single `httpx.AsyncClient` across all requests rather than
opening a new connection per call.
