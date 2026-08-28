from __future__ import annotations

import os

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"


def complete(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_new_tokens: int = 800,
    temperature: float = 0.1,
) -> str:
    """Runs one classification prompt through the Hugging Face Inference API (free tier).

    Requires HF_TOKEN env var: create a free token at
    https://huggingface.co/settings/tokens (read access is enough).
    """
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "HF_TOKEN environment variable is not set. "
            "Create a free access token at https://huggingface.co/settings/tokens "
            "and set it before running the pipeline."
        )

    client = InferenceClient(model=model, token=token, provider="auto")
    response = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_new_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(complete("Reply with the JSON object {\"ok\": true} and nothing else."))
