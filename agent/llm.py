"""Model calls through any OpenAI-compatible API, and the one tool the model can call.

Groq's free tier is the default. Any other OpenAI-compatible endpoint (OpenRouter,
Gemini's compatibility endpoint, a local Ollama) works by setting these variables:

    CAD_AGENT_API_KEY      the key (GROQ_API_KEY is used when this is not set)
    CAD_AGENT_BASE_URL     default https://api.groq.com/openai/v1
    CAD_AGENT_MODEL        default openai/gpt-oss-120b
    CAD_AGENT_REASONING    reasoning effort for reasoning models, default "low";
                           set it to an empty string for models without one
"""

import os

from openai import OpenAI

RUN_AND_CHECK = {
    "type": "function",
    "function": {
        "name": "run_and_check",
        "description": (
            "Run a complete CadQuery script that assigns the finished part to a variable named "
            "`result`, then measure the part against the spec. Returns PASS, or every violation "
            "found, with measured and expected values."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "The complete Python script."}},
            "required": ["code"],
        },
    },
}


class LLM:
    def __init__(self, temperature: float = 1.0, seed: int | None = None):
        self.model = os.environ.get("CAD_AGENT_MODEL", "openai/gpt-oss-120b")
        self.client = OpenAI(
            base_url=os.environ.get("CAD_AGENT_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=os.environ.get("CAD_AGENT_API_KEY") or os.environ.get("GROQ_API_KEY"),
            max_retries=8,  # backs off on 429s, honouring the server's retry-after
            timeout=180,
        )
        self.options = {"temperature": temperature}
        if seed is not None:
            self.options["seed"] = seed
        if effort := os.environ.get("CAD_AGENT_REASONING", "low"):
            self.options["reasoning_effort"] = effort

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """One completion. Returns (message, usage) as the OpenAI client gives them."""
        extra = {"tools": tools, "tool_choice": "required"} if tools else {}
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, **self.options, **extra
        )
        return response.choices[0].message, response.usage
