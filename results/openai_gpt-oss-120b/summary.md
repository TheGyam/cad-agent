Model: `openai/gpt-oss-120b`, 1 run(s) per condition, 30 specs per run.

| Metric | without memory | with memory |
|---|---|---|
| Specs passed within 5 attempts | 63% | 47% |
| Passed on the first attempt | 13% | 7% |
| First attempt ran but was wrong | 33% | 27% |
| First attempt did not run | 53% | 67% |
| Mean attempts, specs that passed | 2.58 | 3.00 |
| Tokens per spec | 4,069 | 5,276 |

Most frequent failure in specs that still failed, by condition:

- without memory: `hole_count` (4), `runtime_error` (2), `invalid_solid` (2), `shape_mismatch` (1), `hole_position` (1), `no_code` (1)
- with memory: `hole_count` (8), `runtime_error` (2), `invalid_solid` (2), `volume` (2), `no_code` (1), `wall_thickness` (1)
