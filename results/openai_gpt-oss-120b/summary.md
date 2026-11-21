Model: `openai/gpt-oss-120b`, 30 specs per run. Runs: without memory 3, memory v1 1, memory v2 1, guided 3.

| Metric | without memory | memory v1 | memory v2 | guided |
|---|---|---|---|---|
| Specs passed within 5 attempts | 59% ± 8 | 47% | 47% | 76% ± 2 |
| Passed on the first attempt | 13% | 7% | 17% | 39% |
| First attempt ran but was wrong | 41% | 27% | 27% | 39% |
| First attempt did not run | 46% | 67% | 57% | 22% |
| Mean attempts, specs that passed | 2.45 | 3.00 | 2.21 | 1.91 |
| Attempts rejected as malformed tool calls | 5% | 20% | 10% | 12% |
| Tokens per spec | 4,102 | 5,276 | 4,828 | 4,345 |

Paired by spec against the run without memory (exact McNemar test):

- memory v1: 6 passed only without memory, 1 only with it, p = 0.125
- memory v2: 7 passed only without memory, 2 only with it, p = 0.180
- guided: 4 passed only without memory, 19 only with it, p = 0.003

Most frequent failure in specs that still failed, by condition:

- without memory: `hole_count` (11), `runtime_error` (9), `invalid_solid` (6), `shape_mismatch` (4), `no_code` (4), `hole_position` (2), `hole_depth` (1)
- memory v1: `hole_count` (8), `runtime_error` (2), `invalid_solid` (2), `volume` (2), `no_code` (1), `wall_thickness` (1)
- memory v2: `runtime_error` (4), `invalid_solid` (3), `shape_mismatch` (2), `hole_count` (2), `hole_depth` (2), `syntax_error` (1), `no_code` (1), `volume` (1)
- guided: `hole_count` (6), `no_code` (5), `runtime_error` (4), `shape_mismatch` (3), `volume` (2), `hole_depth` (2)
