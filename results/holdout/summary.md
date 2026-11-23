Model: `openai/gpt-oss-120b`, 12 specs per run. Runs: without memory 3, guided 3.

| Metric | without memory | guided |
|---|---|---|
| Specs passed within 5 attempts | 47% ± 10 | 75% ± 0 |
| Passed on the first attempt | 11% | 44% |
| First attempt ran but was wrong | 47% | 44% |
| First attempt did not run | 42% | 11% |
| Mean attempts, specs that passed | 2.59 | 1.63 |
| Attempts rejected as malformed tool calls | 4% | 7% |
| Tokens per spec | 4,418 | 4,147 |

Paired by spec against the run without memory (exact McNemar test):

- guided: 2 passed only without memory, 12 only with it, p = 0.013

Most frequent failure in specs that still failed, by condition:

- without memory: `runtime_error` (6), `hole_count` (6), `shape_mismatch` (2), `no_code` (2), `invalid_solid` (2), `hole_position` (1)
- guided: `runtime_error` (4), `shape_mismatch` (2), `hole_count` (1), `volume` (1), `hole_position` (1)
