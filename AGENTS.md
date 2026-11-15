# Working on cad-agent as an agent

Read by every coding agent on this repo (Claude reads it through `CLAUDE.md`).

## Before writing code

Read `ARCHITECTURE.md`. It is short and its rules are enforced in review.

- Stay inside what the task asks. If something outside it looks wrong, mention it
  instead of fixing it.
- Don't add a dependency unless the task needs it.
- Never commit secrets, API keys or virtual environments.
- Never edit the logs in `results/`. They are the evidence for the README's numbers.

## Checks

```
pip install -e ".[dev]"
pytest
```

The suite needs no API key: the model is replaced by a scripted one in tests.
It runs every spec's reference and broken parts, so it takes about a minute.

Report only what you actually did and saw: a check you didn't run is "not run",
never "passed". A benchmark number you didn't produce from the logs is not a
result.

## Commits, pull requests and comments

- **No AI authorship.** Commits are authored by the owner's git identity. Never
  add `Co-Authored-By`, "Generated with", session links or any other line naming
  an AI tool or model to a commit, pull request or comment.
- **Simple, natural English.** Write commit messages, PR titles and
  descriptions, and review comments so anyone can follow them: short full
  sentences that say what changes and why, with no jargon, internal ids or tool
  names.
- Commit subjects use a conventional prefix: `feat(checker): ...`,
  `fix(runner): ...`, `docs: ...`. Say what changes, in plain words.
