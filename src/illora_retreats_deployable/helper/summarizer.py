# summarizer.py

import os
import json
from groq import Groq
from dotenv import load_dotenv
import logging

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

LOG_PATH = 'bot.log'
SUMMARY_OUTPUT_PATH = "summary_log.jsonl"


def extract_conversations(log_file_path):
    sessions = {}

    with open(log_file_path, "r", encoding="ISO-8859-1") as f:
        for line in f:
            if "INFO" not in line:
                continue

            try:
                timestamp, _, log_body = line.partition(" | web | INFO | ")
                source, session_id, user_input, response, *rest = log_body.strip().split(" | ")
                intent = rest[0].replace("Intent: ", "") if rest else None

                if session_id not in sessions:
                    sessions[session_id] = []

                sessions[session_id].append({
                    "user": user_input,
                    "bot": response,
                    "intent": intent,
                    "timestamp": timestamp
                })
            except Exception:
                continue  # skip malformed lines

    return sessions


def get_existing_session_ids(summary_path):
    existing_ids = set()
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="ISO-8859-1") as f:
            for line in f:
                try:
                    existing_ids.add(json.loads(line)["session_id"])
                except:
                    continue
    return existing_ids


def summarize_with_groq(session_id, messages):
    chat_log = ""
    for msg in messages:
        chat_log += f"User: {msg['user']}\nBot: {msg['bot']}\n"

    prompt = f"""
You are a summarization agent for a hotel chatbot named 'AI Chieftain', deployed at a luxury hotel to assist guests with queries about services, amenities, booking, restaurant, travel desk, etc.

Summarize the conversation between the guest and the bot in clear bullet points.
Then write a professional and polite follow-up message from the hotel side, reiterating what was discussed and offering further assistance.

Conversation:
{chat_log}
"""

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return completion.choices[0].message.content.strip()


def save_summary(session_id, summary_response):

    summary, follow_up = summary_response.split("Follow-up", 1)
    follow_up_email = "Follow-up" + follow_up

    with open(SUMMARY_OUTPUT_PATH, "a", encoding="ISO-8859-1") as f:
        f.write(json.dumps({
            "session_id": session_id,
            "summary": summary.strip(),
            "follow_up_email": follow_up_email.strip()
        }) + "\n")


def main():
    sessions = extract_conversations(LOG_PATH)
    existing_ids = get_existing_session_ids(SUMMARY_OUTPUT_PATH)
    print(f"Total sessions found: {len(sessions)} | Already summarized: {len(existing_ids)}")

    for session_id, messages in sessions.items():
        if session_id in existing_ids:
            print(f"Skipping already summarized session: {session_id}")
            continue

        print(f"Summarizing session: {session_id}")
        try:
            summary = summarize_with_groq(session_id, messages)
            save_summary(session_id, summary)
            print(f"Saved summary for session {session_id}")
        except Exception as e:
            print(f"Failed to summarize session {session_id}: {e}")


if __name__ == "__main__":
    main()
