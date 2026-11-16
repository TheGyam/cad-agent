"""Lessons learned from earlier parts, kept in a JSON file and added to the prompt.

After a part that needed fixing or failed, the model is asked for one general
lesson. A lesson is kept only if it is general (it repeats no number from the
spec, so it cannot carry the answer) and new (not nearly the same as one already
kept). At most `limit` lessons go into a prompt: same family first, then newest.

ponytail: no embeddings or vector search; with tens of lessons, family plus
recency is enough. Rank by similarity if the store grows to hundreds.

Two versions, both kept so each benchmark condition stays reproducible:

- v1 (condition B): up to 10 lessons, up to 40 words, any wording.
- v2 (condition C, `strict=True`): built from what v1's run showed. With four or
  more lessons in the prompt, the model's tool calls were rejected far more often
  (21-32% against 5%), so v2 shows at most 3. Lessons are made plain ASCII (v1's had
  curly quotes and non-breaking hyphens), kept to 30 words, and must name a
  specific CadQuery call, which rules out generic "always verify" advice.
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

LESSON_PROMPT_V2 = """You just worked on this CAD part:

{spec}

Your attempts and what the checker reported:
{history}

Write ONE lesson that would have avoided the first mistake when modelling a
different part. Name the specific CadQuery method or selector involved (for
example `.hole()` or `.faces()`), say what goes wrong and what to do instead.
One sentence, at most 30 words, plain ASCII, no numbers from this part. Reply
with the sentence only."""

# Typographic characters seen in v1's lessons, and their plain equivalents.
ASCII = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2010": "-",
                       "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2026": "...",
                       "\u00a0": " ", "\u202f": " "})
CALL = re.compile(r"\w+\(")

NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Lessons must be about CAD. Without this filter the model learned "always include the
# `code` argument in run_and_check" from rejected tool calls, crowding out real lessons.
HARNESS = re.compile(r"run_and_check|tool call|\bchecker\b|`code` argument", re.IGNORECASE)


class Memory:
    def __init__(self, path: Path, limit: int | None = None, strict: bool = False):
        self.path = Path(path)
        self.strict = strict
        self.limit = limit if limit is not None else (3 if strict else 10)
        self.lessons = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def relevant(self, family: str) -> list[str]:
        ranked = sorted(enumerate(self.lessons), key=lambda il: (il[1]["family"] == family, il[0]), reverse=True)
        return [lesson["text"] for _, lesson in ranked[: self.limit]]

    def add(self, text: str, spec: dict) -> str | None:
        """Keep the lesson if it is acceptable. Returns why it was refused, or None."""
        text = " ".join(text.split()).lstrip("-* ").strip()
        if not text or len(text) > 400:
            return "empty or too long"
        if self.strict:
            text = text.translate(ASCII)
            if not text.isascii():
                return "not plain ASCII"
            if len(text.split()) > 30:
                return "longer than 30 words"
            if not CALL.search(text):
                return "names no CadQuery call"
        if HARNESS.search(text):
            return "about the tool or the checker, not about modelling"
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

    def learn(self, llm, spec: dict, attempts: list[dict]) -> dict | None:
        """Ask the model for a lesson from these attempts and try to keep it.

        Attempts with no code (the tool call itself was rejected) say nothing about
        modelling, so they are left out; with none left, no lesson is asked for.
        """
        attempts = [a for a in attempts if a["categories"] != ["no_code"]]
        if not attempts or (len(attempts) == 1 and attempts[0]["passed"]):
            return None
        history = "\n".join(
            f"Attempt {a['attempt']}: " + ("PASS" if a["passed"] else
                                           "; ".join(f"{v['category']}: {v['message']}" for v in a["violations"]))
            for a in attempts
        )
        prompt = LESSON_PROMPT_V2 if self.strict else LESSON_PROMPT
        message, usage = llm.chat([{"role": "user", "content": prompt.format(spec=spec["text"].strip(),
                                                                                    history=history)}])
        text = (message.content or "").strip().splitlines()[0] if (message.content or "").strip() else ""
        refused = self.add(text, spec)
        return {"lesson": text, "kept": refused is None, "refused": refused,
                "tokens": usage.total_tokens if usage else 0}
