"""The one place that calls the model. The key and base URL come from the environment or a local .env."""

from dotenv import load_dotenv
from openai import OpenAI

MODEL = "gemma-4-E4B-it"


def load_complete():
    """A function from messages, and optional tools, to the model's message. temperature=0 so runs repeat."""
    load_dotenv()
    client = OpenAI(max_retries=8)  # the class proxy limits tokens per minute, so a 429 clears within a minute

    def complete(messages, tools=None):
        extra = {"tools": tools} if tools else {}
        return client.chat.completions.create(model=MODEL, temperature=0, messages=messages, **extra).choices[0].message

    return complete
