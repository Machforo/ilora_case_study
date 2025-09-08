import streamlit as st
import os
import json
import pandas as pd
from pathlib import Path

# === Replace with your actual import paths ===
from helper.qa_generator import generate_qa_pairs  # used for manual form
from helper.document_ingest import extract_document
from helper.summarizer_data import summarize_text
from helper.qa_generator_data import generate_qa_pairs as generate_qa_pairs_from_summary
from helper.utils_data import ensure_dir
from config import QA_OUTPUT_CSV, QA_PAIR_COUNT, UPLOAD_TEMP_DIR

# Streamlit page setup
st.set_page_config(page_title="Hotel Concierge Q&A Generator", layout="wide")
os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)


st.title("🏨 Hotel Concierge Bot — Q&A Generator")

# Mode selection
mode = st.selectbox("Choose how you want to generate Q&A pairs:", ["📋 Fill Hotel Form", "📄 Upload Hotel Documents"])

# Shared output file
OUTPUT_FILENAME = "qa_pairs.csv"

# ------------------------- #
# 📋 FORM-BASED Q&A LOGIC
# ------------------------- #
if mode == "📋 Fill Hotel Form":
    st.markdown("Fill in your hotel details. We'll generate Q&A pairs for your concierge bot.")

    with st.form("hotel_form"):
        name = st.text_input("Hotel Name")
        room_types = st.text_input("Room types and pricing (e.g., Deluxe ₹4000, Suite ₹7000)")
        amenities = st.text_input("Amenities (e.g., Spa, Gym, Pool)")
        check_in_out = st.text_input("Check-in and Check-out times (e.g., 2 PM / 11 AM)")
        restaurant = st.text_input("Do you have a restaurant? What cuisines are served?")
        transport = st.text_input("Do you provide airport pickup/drop?")
        custom_notes = st.text_area("Other policies or services")

        submitted = st.form_submit_button("Generate Q&A")

    if submitted:
        hotel_info = {
            "name": name,
            "room_types": room_types,
            "amenities": amenities,
            "check_in_out": check_in_out,
            "restaurant": restaurant,
            "transport": transport,
            "custom_notes": custom_notes
        }

        with st.spinner("Generating Q&A pairs..."):
            try:
                qa_pairs = generate_qa_pairs(hotel_info)

                with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
                    for line in qa_pairs:
                        f.write(line.strip() + "\n")

                st.success(f"✅ Q&A dataset saved as `{OUTPUT_FILENAME}`")
                st.download_button("📥 Download Q&A CSV", data="\n".join(qa_pairs), file_name=OUTPUT_FILENAME)

            except Exception as e:
                st.error(f"❌ Error: {e}")

# ------------------------- #
# 📄 DOCUMENT-BASED Q&A LOGIC
# ------------------------- #
elif mode == "📄 Upload Hotel Documents":
    st.markdown("""
    Upload documents, summarize them, and generate **150 Q&A pairs per document**.  
    All Q&A pairs are appended to the same file: `qa_pairs.csv`.
    """)

    hotel_name_input = st.text_input("Hotel Name", placeholder="e.g., LUXORIA SUITES")

    uploaded_files = st.file_uploader(
        "Upload hotel documents",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True
    )

    if st.button("Run Pipeline", disabled=not uploaded_files or not hotel_name_input.strip()):
        if not hotel_name_input.strip():
            st.warning("Please enter the hotel name before proceeding.")
            st.stop()
        if not uploaded_files:
            st.warning("Please upload at least one document.")
            st.stop()

        hotel_context = hotel_name_input.strip()
        st.markdown(f"**Hotel context for QA generation:** {hotel_context}")

        failed = []
        all_pairs = []

        with st.spinner("Processing documents..."):
            for uploaded in uploaded_files:
                st.markdown(f"## 📄 Processing: **{uploaded.name}**")
                temp_path = Path(UPLOAD_TEMP_DIR) / uploaded.name

                try:
                    with open(temp_path, "wb") as f:
                        f.write(uploaded.getbuffer())
                except Exception as e:
                    st.error(f"Failed to save {uploaded.name}: {e}")
                    failed.append(uploaded.name)
                    continue

                # Extract text
                try:
                    text = extract_document(str(temp_path))
                    st.success(f"Extracted text from {uploaded.name}")
                except Exception as e:
                    st.error(f"Extraction failed: {e}")
                    failed.append(uploaded.name)
                    continue

                # Summarize
                try:
                    summary, _ = summarize_text(uploaded.name, text)
                    st.text_area(f"Summary for {uploaded.name}", value=summary, height=150)
                except Exception as e:
                    st.error(f"Summarization failed: {e}")
                    failed.append(uploaded.name)
                    continue

                # Generate Q&A pairs
                try:
                    raw_response, parsed_pairs = generate_qa_pairs_from_summary(hotel_context, summary, QA_PAIR_COUNT)
                except Exception as e:
                    st.error(f"Q&A generation failed: {e}")
                    failed.append(uploaded.name)
                    continue

                # Show raw & preview
                st.text_area(f"Raw QA Output for {uploaded.name}", value=raw_response, height=200)
                if parsed_pairs:
                    st.dataframe(pd.DataFrame(parsed_pairs, columns=["question", "answer"]).head(10))
                else:
                    st.warning("No Q&A pairs parsed.")
                    continue

                # Save/append to output file
                if os.path.exists(OUTPUT_FILENAME):
                    existing_df = pd.read_csv(OUTPUT_FILENAME, header=None, names=["question", "answer"])
                    new_df = pd.DataFrame(parsed_pairs, columns=["question", "answer"])
                    final_df = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    final_df = pd.DataFrame(parsed_pairs, columns=["question", "answer"])

                final_df.to_csv(OUTPUT_FILENAME, index=False, header=False)
                st.success(f"Appended {len(parsed_pairs)} Q&A pairs for {uploaded.name}")
                all_pairs.extend(parsed_pairs)

        if all_pairs:
            st.markdown("### All Q&A Pairs This Session")
            st.dataframe(pd.DataFrame(all_pairs, columns=["question", "answer"]))

            with open(OUTPUT_FILENAME, "rb") as f:
                st.download_button("📥 Download Combined Q&A CSV", data=f, file_name=OUTPUT_FILENAME, mime="text/csv")

        if failed:
            st.warning(f"Some files failed to process: {', '.join(failed)}")


## qa_pairs database --> new database --_feed