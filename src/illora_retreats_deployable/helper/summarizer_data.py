import os
import time
from typing import Tuple

from config import LLM_MODEL, MAX_SUMMARY_TOKENS
from utils_data import extract_hotel_name

# Groq SDK
try:
    from groq import Groq
except ImportError:
    raise ImportError("Groq SDK not installed. Run `pip install groq` to install it.")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not set in environment variables.")

_client = Groq(api_key=GROQ_API_KEY)

def call_llm_model(model: str, prompt: str, max_tokens: int, temperature: float) -> str:
    """
    Calls Groq's model and returns generated text. Retries on failure.
    """
    retries = 3
    backoff_base = 1.0
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = _client.chat.completions.create(
                model=model or LLM_MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = resp.choices[0].message.content
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
            return content.strip()
        except Exception as e:
            last_exc = e
            sleep_time = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_time)
    raise RuntimeError(f"Failed to call Groq after {retries} attempts. Last error: {last_exc}")

def summarize_text(doc_name: str, text: str) -> Tuple[str, str]:
    hotel_name = extract_hotel_name(text)
    prompt = f"""You are an assistant summarizing the following document from the hotel titled '{hotel_name}' (source file: {doc_name}).
Extract key facts, policies, services, named entities (room types, pricing if present, guest policies, amenities, check-in/out rules, payment methods, contact info, special instructions), and anything a guest or staff would need to know, in concise bullet form. Prepend at the top a single line stating the inferred hotel name.

Document content:
\"\"\"{text[:4000]}\"\"\"

Provide the summary as bullet points."""
    summary = call_llm_model(
        model=LLM_MODEL,
        prompt=prompt,
        max_tokens=MAX_SUMMARY_TOKENS,
        temperature=0.2
    )
    return summary.strip(), hotel_name
