Model: `openai/gpt-oss-120b`, 1 run(s) per condition, 30 specs per run.

| Metric | without memory | memory v1 | memory v2 | guided |
|---|---|---|---|---|
| Specs passed within 5 attempts | 63% | 47% | 47% | 77% |
| Passed on the first attempt | 13% | 7% | 17% | 37% |
| First attempt ran but was wrong | 33% | 27% | 27% | 30% |
| First attempt did not run | 53% | 67% | 57% | 33% |
| Mean attempts, specs that passed | 2.58 | 3.00 | 2.21 | 2.13 |
| Attempts rejected as malformed tool calls | 5% | 20% | 10% | 14% |
| Tokens per spec | 4,069 | 5,276 | 4,828 | 4,472 |

Paired by spec against the run without memory (exact McNemar test):

- memory v1: 6 passed only without memory, 1 only with it, p = 0.125
- memory v2: 7 passed only without memory, 2 only with it, p = 0.180
- guided: 1 passed only without memory, 5 only with it, p = 0.219

Most frequent failure in specs that still failed, by condition:

- without memory: `hole_count` (4), `runtime_error` (2), `invalid_solid` (2), `shape_mismatch` (1), `hole_position` (1), `no_code` (1)
- memory v1: `hole_count` (8), `runtime_error` (2), `invalid_solid` (2), `volume` (2), `no_code` (1), `wall_thickness` (1)
- memory v2: `runtime_error` (4), `invalid_solid` (3), `shape_mismatch` (2), `hole_count` (2), `hole_depth` (2), `syntax_error` (1), `no_code` (1), `volume` (1)
- guided: `hole_count` (2), `shape_mismatch` (2), `no_code` (1), `volume` (1), `hole_depth` (1)
