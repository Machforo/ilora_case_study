import os
import re
from fuzzywuzzy import fuzz

def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()

def ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def dedupe_answers(qa_pairs, similarity_threshold=90):
    unique = []
    seen = []
    for q, a in qa_pairs:
        is_dup = False
        for existing in seen:
            if fuzz.token_set_ratio(a, existing) >= similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append((q, a))
            seen.append(a)
    return unique

def extract_hotel_name(text: str) -> str:
    """
    Heuristically extract hotel name: patterns like 'Hotel <Name>', '<Name> Suites', title headings, etc.
    """
    patterns = [
        r'Hotel\s+([A-Z][\w& ]{2,})',
        r'([A-Z][\w& ]{2,}Suites?)',
        r'([A-Z][\w& ]{2,}Inn)',
        r'([A-Z][\w& ]{2,}Resort)',
        r'([A-Z][\w& ]{2,}Hotel)',
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            return name.title()

    # Fallback: first non-empty line that looks like a heading
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        first = lines[0]
        if len(first.split()) <= 6 and (first.isupper() or first.istitle()):
            return first.title()
    return "Unknown Hotel"
