Model: `openai/gpt-oss-120b`, 12 specs per run. Runs: without memory 3, guided 3, guided v2 3.

| Metric | without memory | guided | guided v2 |
|---|---|---|---|
| Specs passed within 5 attempts | 53% ± 13 | 67% ± 8 | 81% ± 5 |
| Passed on the first attempt | 17% | 36% | 44% |
| First attempt ran but was wrong | 33% | 44% | 36% |
| First attempt did not run | 50% | 19% | 19% |
| Mean attempts, specs that passed | 2.37 | 1.71 | 1.62 |
| Attempts rejected as malformed tool calls | 6% | 14% | 4% |
| Tokens per spec | 3,879 | 4,309 | 4,478 |

Paired by spec against the run without memory (exact McNemar test):

- guided: 4 passed only without memory, 9 only with it, p = 0.267
- guided v2: 1 passed only without memory, 11 only with it, p = 0.006

Most frequent failure in specs that still failed, by condition:

- without memory: `hole_count` (10), `runtime_error` (2), `no_code` (2), `invalid_solid` (2), `shape_mismatch` (1)
- guided: `runtime_error` (3), `hole_count` (3), `no_code` (3), `volume` (2), `shape_mismatch` (1)
- guided v2: `hole_count` (3), `volume` (1), `hole_position` (1), `invalid_solid` (1), `shape_mismatch` (1)
