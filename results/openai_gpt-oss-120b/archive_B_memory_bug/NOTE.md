# Archived: first condition-B run (invalid)

These are the 14 specs of the first run with memory, stopped by the daily token
limit on 2026-11-15. They are not used in any result.

The memory had a bug: when the provider rejected a malformed tool call, the model
was still asked for a lesson, and it learned lessons about the tool instead of
about CAD ("always include a run_and_check call with a code argument"). Four of
the thirteen lessons in `lessons_B_run0.json` are like that. The run measured
that bug, not the effect of memory.

Fixed in commit 2f144e1 ("fix(memory): learn only from modelling mistakes, not
rejected tool calls"). Condition B was then rerun from an empty memory.
Condition A was not affected and was kept.
