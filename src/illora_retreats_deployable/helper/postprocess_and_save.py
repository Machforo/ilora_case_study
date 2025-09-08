import re
import pandas as pd
from typing import List, Tuple, Union

from config import QA_OUTPUT_CSV

def sanitize_pair(question: str, answer: str) -> Tuple[str, str]:
    """
    Replace internal commas with semicolons. Preserve the single comma delimiter between
    question and answer. Strip numbering.
    """
    question = re.sub(r'^\s*\d+[\)\.\,]?\s*', '', question).strip()
    answer = answer.strip()

    question = question.replace(',', ';')
    answer = answer.replace(',', ';')

    return question, answer

def finalize_and_write(qa_pairs: Union[List[Tuple[str, str]], List[str]]):
    """
    qa_pairs can be a list of (question, answer) tuples or list of raw lines.
    Normalizes and saves all pairs without deduplication, printing them first.
    """
    print(qa_pairs)
    normalized: List[Tuple[str, str]] = []

    for item in qa_pairs:
        q_raw = None
        a_raw = None

        if isinstance(item, tuple) and len(item) == 2:
            q_raw, a_raw = item
        elif isinstance(item, str):
            line = item.strip()
            # remove leading numbering like "30," "30." "30) "
            line = re.sub(r'^\s*\d+[\)\.\,]?\s*', '', line)
            # try split based on comma after question mark
            m = re.search(r'\?(,)', line)
            if m:
                split_idx = m.end(1)
                q_raw = line[: m.start(1) + 1].strip()  # includes '?'
                a_raw = line[split_idx:].strip()
            else:
                if ',' in line:
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        q_raw = parts[0].strip()
                        a_raw = parts[1].strip()
        # skip if we didn't get valid raw question/answer
        if not q_raw or not a_raw:
            continue

        q_san, a_san = sanitize_pair(q_raw, a_raw)
        if q_san and a_san:
            normalized.append((q_san, a_san))

    # Print all normalized pairs for debugging
    print("=== Normalized QA Pairs ===")
    for q, a in normalized:
        print(f"{q},{a}")
    print("=== End Normalized QA Pairs ===")

    # Save to CSV with no header
    df = pd.DataFrame(normalized, columns=["question", "answer"])
    df.to_csv(QA_OUTPUT_CSV, index=False, header=False)
    print(f"Saved {len(df)} QA pairs to {QA_OUTPUT_CSV}")
    return len(df)
