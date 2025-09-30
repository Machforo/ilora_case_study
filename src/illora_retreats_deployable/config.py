import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Central configuration for AI Chieftain
    """

    GSHEET_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbxQjqqC_KM-zKlXAf2fs6B3jUjBBvuIES0a2VA4guZP0rZMR7A8JJGxDIUEzmcSZWFJ/exec"
    GSHEET_QNA_SHEET = "QnA_Manager"
    GSHEET_DOS_SHEET = "Dos and Donts"
    GSHEET_CAMPAIGN_SHEET = "Campaigns_Manager"

    # ------------------------
    # LLM Provider (switch between "openai" and "groq")
    # ------------------------
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

    # ------------------------
    # OpenAI (GPT models & embeddings)
    # ------------------------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "openai/gpt-oss-120b")  
    OPENAI_EMBEDDING_MODEL = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")

    # ------------------------
    # Groq (fallback)
    # ------------------------
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
    GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_API_BASE  = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")

    # ------------------------
    # Stripe Payments
    # ------------------------
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

    # ------------------------
    # Data paths
    # ------------------------
    CSV_DATA_PATH = os.getenv("CSV_DATA_PATH", "data\\qa_pairs.csv")

    
    # ------------------------
    # QNA generation
    # ------------------------
    
    RAW_DOCS_DIR = "data\\raw_docs"
    SUMMARY_OUTPUT_PATH =  "data\\combined_summary.txt"
    QA_OUTPUT_CSV =  "data\\qa_pairs.csv"
    UPLOAD_TEMP_DIR = "Hotel_docs"

    # Model / API config
    MAX_SUMMARY_TOKENS = int(os.getenv("MAX_SUMMARY_TOKENS", "500"))
    QA_PAIR_COUNT = int(os.getenv("QA_PAIR_COUNT", "100"))

    # --------------------------
    # Github Token for AI use
    # --------------------------

    endpoint = "https://models.github.ai/inference"
    model = "openai/gpt-5"
    GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]








