"""Lessons learned from earlier parts, kept in a JSON file and added to the prompt.

After a part that needed fixing or failed, the model is asked for one general
lesson. A lesson is kept only if it is general (it repeats no number from the
spec, so it cannot carry the answer) and new (not nearly the same as one already
kept). At most `limit` lessons go into a prompt: same family first, then newest.

ponytail: no embeddings or vector search; with tens of lessons, family plus
recency is enough. Rank by similarity if the store grows to hundreds.
"""

import difflib
import json
import re
from pathlib import Path

LESSON_PROMPT = """You just worked on this CAD part:

{spec}

Your attempts and what the checker reported:
{history}

Write ONE lesson that would have avoided the first mistake when modelling a
different part. It must be general CadQuery or modelling advice: one sentence,
at most 40 words, with no dimensions or numbers from this part. Reply with the
sentence only."""

NUMBER = re.compile(r"\d+(?:\.\d+)?")


class Memory:
    def __init__(self, path: Path, limit: int = 10):
        self.path = Path(path)
        self.limit = limit
        self.lessons = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def relevant(self, family: str) -> list[str]:
        ranked = sorted(enumerate(self.lessons), key=lambda il: (il[1]["family"] == family, il[0]), reverse=True)
        return [lesson["text"] for _, lesson in ranked[: self.limit]]

    def add(self, text: str, spec: dict) -> str | None:
        """Keep the lesson if it is acceptable. Returns why it was refused, or None."""
        text = " ".join(text.split()).lstrip("-* ").strip()
        if not text or len(text) > 400:
            return "empty or too long"
        leaked = set(NUMBER.findall(text)) & set(NUMBER.findall(spec["text"])) - {"0", "1"}
        if leaked:
            return f"repeats numbers from the spec: {sorted(leaked)}"
        for lesson in self.lessons:
            if difflib.SequenceMatcher(None, text.lower(), lesson["text"].lower()).ratio() >= 0.8:
                return "nearly the same as a lesson already kept"
        self.lessons.append({"text": text, "spec": spec["id"], "family": spec["family"]})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=2), encoding="utf-8")
        return None

    def learn(self, llm, spec: dict, attempts: list[dict]) -> dict:
        """Ask the model for a lesson from these attempts and try to keep it."""
        history = "\n".join(
            f"Attempt {a['attempt']}: " + ("PASS" if a["passed"] else
                                           "; ".join(f"{v['category']}: {v['message']}" for v in a["violations"]))
            for a in attempts
        )
        message, usage = llm.chat([{"role": "user", "content": LESSON_PROMPT.format(spec=spec["text"].strip(),
                                                                                    history=history)}])
        text = (message.content or "").strip().splitlines()[0] if (message.content or "").strip() else ""
        refused = self.add(text, spec)
        return {"lesson": text, "kept": refused is None, "refused": refused,
                "tokens": usage.total_tokens if usage else 0}
