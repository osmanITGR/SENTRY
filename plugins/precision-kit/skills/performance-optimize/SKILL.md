---
name: performance-optimize
description: Make code faster or lighter with measurements, not guesses - define the metric, benchmark/profile to find the real bottleneck, apply the highest-leverage fix, and prove the gain without breaking behaviour. Use for slow pages/screens/endpoints/queries/builds/tests, high CPU/memory/battery/bundle size, lag, timeouts, scaling issues, or any "optimize"/"speed up" request.
---

# Performance Optimize

No optimization without a before/after number.

## 1. Define the target
Metric + workload + goal: "p95 of GET /scan under 50 rps: 800 ms -> < 200 ms",
"cold start 4.1 s -> < 2 s", "JS bundle 1.8 MB -> < 1 MB", "frame time < 16 ms".

## 2. Measure the baseline (reproducible, same machine, warm-up, >= 3 runs)
| Area | Tools |
|------|-------|
| Python | `python -m cProfile -s cumtime`, `py-spy record`, `pytest-benchmark`, `tracemalloc` |
| Node/JS | `node --cpu-prof`, `clinic`, `0x`, Chrome DevTools Performance, `vitest bench` |
| Web | Lighthouse, Web Vitals (LCP/INP/CLS), bundle analyzer, network waterfall |
| Go | `go test -bench . -benchmem`, `pprof` |
| Rust | `cargo bench` (criterion), `cargo flamegraph` |
| JVM/Android | Android Studio profiler, Macrobenchmark, `systrace`/Perfetto |
| Flutter | DevTools performance overlay, `--profile` mode |
| .NET | BenchmarkDotNet, `dotnet-trace`, `dotnet-counters` |
| DB | `EXPLAIN ANALYZE`, slow-query log, query count per request |
| Embedded | cycle counters/`micros()` around sections, free-heap logging |

## 3. Find the bottleneck (profile says where; don't guess)
Typical high-leverage causes, check in this order:
1. Wrong algorithm/data structure (O(n^2) loops, list lookups that should be sets/maps).
2. I/O patterns: N+1 queries, missing index, chatty network calls, no batching,
   sync I/O on hot or UI thread, missing pagination/streaming.
3. Repeated work: recomputation in loops/renders, missing memoization/caching,
   unnecessary re-renders/rebuilds, re-parsing.
4. Payload size: over-fetching, uncompressed assets, huge bundles (code-split,
   tree-shake, lazy-load), unoptimised images.
5. Memory: leaks (listeners/subscriptions not disposed), unbounded caches/queues,
   large copies.
6. Concurrency: serial awaits that could be parallel, lock contention.

## 4. Fix one thing, re-measure
Apply the single biggest fix, rerun the same benchmark, record the delta.
Keep it only if the gain is real (beyond noise) and code stays readable.
Caches need an invalidation story and a size bound.

## 5. Prove nothing broke
Full `verification-gate`; add a benchmark or a performance regression test
(e.g. query-count assertion, bundle-size budget) when the project supports it.

## Report
`metric: before -> after (x faster), workload, what changed, trade-offs`.
