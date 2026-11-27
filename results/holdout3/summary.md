Model: `openai/gpt-oss-120b`, 12 specs per run. Runs: without memory 3, guided v2 3, guided v3 3.

| Metric | without memory | guided v2 | guided v3 |
|---|---|---|---|
| Specs passed within 5 attempts | 39% ± 5 | 75% ± 8 | 69% ± 5 |
| Passed on the first attempt | 11% | 36% | 31% |
| First attempt ran but was wrong | 39% | 36% | 36% |
| First attempt did not run | 50% | 28% | 33% |
| Mean attempts, specs that passed | 2.36 | 1.70 | 1.80 |
| Attempts rejected as malformed tool calls | 6% | 12% | 5% |
| Tokens per spec | 4,363 | 4,347 | 6,396 |

Paired by spec against the run without memory (exact McNemar test):

- guided v2: 2 passed only without memory, 15 only with it, p = 0.002
- guided v3: 2 passed only without memory, 13 only with it, p = 0.007

Most frequent failure in specs that still failed, by condition:

- without memory: `hole_count` (10), `runtime_error` (5), `hole_depth` (3), `no_code` (2), `invalid_solid` (2)
- guided v2: `invalid_solid` (2), `runtime_error` (1), `hole_depth` (1), `no_code` (1), `hole_diameter` (1), `hole_position` (1), `shape_mismatch` (1), `hole_count` (1)
- guided v3: `runtime_error` (4), `hole_position` (3), `shape_mismatch` (1), `volume` (1), `hole_count` (1), `no_code` (1)
