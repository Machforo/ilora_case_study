import os
from dotenv import load_dotenv
from groq import Groq  # Ensure `groq` package is installed
from config import Config

load_dotenv()

# Create the Groq client using the API key
client = Groq(api_key=Config.GROQ_API_KEY)

def generate_qa_pairs(hotel_info: dict) -> list:
    prompt = f"""
You are a hotel concierge bot setup assistant. Generate exactly detailed 50 Q&A pairs based on the following hotel information (note ony include 1 comma per line):

Hotel Name: {hotel_info['name']}
Room Types & Prices: {hotel_info['room_types']}
Amenities: {hotel_info['amenities']}
Check-in/Out: {hotel_info['check_in_out']}
Restaurant: {hotel_info['restaurant']}
Transport: {hotel_info['transport']}
Other Notes: {hotel_info['custom_notes']}

Each line should be in the format:
<question>,<answer>

There must be exactly one comma per line and no additional commas. Include explanations.
Respond only with the lines.

"""

    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=Config.MODEL_NAME
    )

    return response.choices[0].message.content.strip().split("\n")
