import os
import time
import re
from typing import List, Tuple

from config_data import LLM_MODEL, QA_PAIR_COUNT

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
    Calls Groq's model and returns generated text with retry.
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
            time.sleep(backoff_base * (2 ** (attempt - 1)))
    raise RuntimeError(f"Failed to call Groq after {retries} attempts. Last error: {last_exc}")

# --- Parsing / sanitization logic (same as in postprocess_and_save.py debug harness) ---

def sanitize_pair(question: str, answer: str) -> Tuple[str, str]:
    question = re.sub(r'^\s*\d+[\)\.\,]?\s*', '', question).strip()
    answer = answer.strip()
    question = question.replace(',', ';')
    answer = answer.replace(',', ';')
    question = re.sub(r';+\s*$', '', question).strip()
    answer = re.sub(r';+\s*$', '', answer).strip()
    return question, answer

def parse_and_sanitize_pairs(raw: str) -> List[Tuple[str, str]]:
    pairs = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        # Remove numbering at start
        line_clean = re.sub(r'^\s*\d+[\)\.\,]?\s*', '', line).strip()

        # Try to split on ", " right after a question mark
        m = re.search(r'\?(,)', line_clean)
        if m:
            split_idx = m.end(1)
            q_raw = line_clean[: m.start(1) + 1].strip()  # includes '?'
            a_raw = line_clean[split_idx:].strip()
        elif ',' in line_clean:
            parts = line_clean.split(',', 1)
            if len(parts) == 2:
                q_raw, a_raw = parts[0].strip(), parts[1].strip()
            else:
                continue
        else:
            continue

        q_san, a_san = sanitize_pair(q_raw, a_raw)
        if q_san and a_san:
            pairs.append((q_san, a_san))
    return pairs

# --- Main function ---

def generate_qa_pairs(hotel_context: str, combined_summary: str, desired_count: int) -> Tuple[str, List[Tuple[str, str]]]:
    prompt = f"""
You are an AI assistant for the hotel(s): {hotel_context}.
Given the following aggregated summary of all hotel documents, generate {desired_count} useful and relevant question-answer pairs a guest or front-desk agent might ask or need.

Requirements:
- Output exactly one question and one answer per line.
- Format each line as: <question>,<answer>
- Avoid using commas inside question or answer; use semicolons if needed.
- Answers must be unique in meaning; avoid near-duplicates.
- Questions should be conversational and clear.
- If multiple hotels are in context, make it generic enough or specify when relevant.

Example:
What time is check-in?,Check-in is after 2 PM.
Do you have Wi-Fi?,Yes; complimentary Wi-Fi is available throughout the hotel.

Summary:
\"\"\"{combined_summary}\"\"\"
"""
    raw_response = call_llm_model(
        model=LLM_MODEL,
        prompt=prompt,
        max_tokens=1500,
        temperature=0.3
    )

    parsed_pairs = parse_and_sanitize_pairs(raw_response)

    return raw_response, parsed_pairs
