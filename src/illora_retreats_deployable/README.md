# 🛎️ AI Chieftain – Concierge Bot for  ILLORA RETREATS

**AI Chieftain** is an advanced AI concierge assistant designed specifically for **LUXORIA SUITES**, enabling guests and visitors to interact via **Web**, **Voice**, **QR**, and **WhatsApp**. It integrates cutting-edge **LLMs**, **Stripe**, **LangChain**, **Twilio**, and **Streamlit** with features like **room payments**, **chat summaries**, and a complete **property management system (PMS)** backend.

---

## 🎥 Demo Video
**https://drive.google.com/file/d/1_mAcV0OX2tLDVl-vT17lBcic5GsFxKrv/view?usp=sharing**

---

## 🚀 Features

- Web chatbot with voice & QR code access
- Guest/non-guest user filtering for tailored service
- LLM-backed chat responses (via Groq + LangChain)
- Integrated Stripe payment gateway (₹2000 advance/cash mode, full online mode)
- Auto-generated payment links via WhatsApp
- Twilio WhatsApp integration
- Room pricing logic (₹4000–₹8000/night based on type & duration)
- Chat session summary generation
- Centralized logging of interactions across all channels
- Admin dashboard with session analytics and log exports
- PMS backend & AI assistant for dataset creation

---

## 📁 Project Structure


```
AI_CHIEFTAIN_BOT_ATHARVKUMAR/
├── app/
│   ├── __pycache__/                    # Cached bytecode files
│   ├── agents/
│   │   ├── __pycache__/
│   │   └── qa_agent.py                 # Core LLM logic for answering queries
│   ├── assets/
│   │   └── logo.jpg                    # Logo used in the UI
│   ├── interfaces/
│   │   ├── __pycache__/
│   │   ├── cli_interface.py           # CLI version of the bot
│   │   └── web_ui.py                  # Streamlit web interface
│   ├── logs/
│   │   └── chat_logs.csv              # Centralized chat logs
│   ├── services/
│   │   ├── __pycache__/
│   │   ├── intent_classifier.py 
|       ├── payment_gateway.py 
|       ├── summarizer.py.py           # Basic intent classification 
│   │   ├── logger.py                  # Logging utilities
│   │   ├── nlu.yml                    # NLU training data (used by Rasa or 
│   │   ├── vector_store.py            # Vector DB (e.g., FAISS) and embeddings
│   │   └── config.py                  # Configurations and constants
├── data/
│   └── hotel_faq.csv     
|   └── AI_assistant_dataset.py         # FAQ dataset used for context retrieval
├── logs/
│   └── bot.log                        # System and error logs
├── .env                               # API keys and environment variables
├── dashboard.py                       # Admin dashboard with analytics
├── main.py                            # CLI entry point
├── mic_test.py                        # Mic/audio debugging script
├── README.md                          # Documentation
├── requirements.txt                   # Python dependencies
├── test_audio.wav                     # Audio test file
└── twilio_webhook.py                  # WhatsApp + Twilio integration
```



---


---

## 🧠 AI Capabilities

| Feature              | Description                                                  |
|----------------------|--------------------------------------------------------------|
| LLM Concierge        | Hotel-specific intelligent responses (Groq + LangChain)      |
| Guest Filtering      | Tailors services to guests vs non-guests                     |
| Payment Generation   | Detects payment intent & sends Stripe link automatically     |
| Voice Chat           | Web mic integration (speech-to-text + TTS)                   |
| Chat Summarizer      | Generates text summary of session interactions               |
| PMS Add-on           | Backend-ready for booking & visitor management               |
| Dataset AI Agent     | Helps hotel staff generate high-quality Q&A pairs            |

---

## ⚙️ Setup Instructions

### 🔐 1. Clone and Environment Setup

```bash
git clone https://github.com/Machforo/AI_Chieftain_Bot.git
cd AI_Chieftain_Bot
python -m venv venv
venv\Scripts\activate   # For Windows
# OR
source venv/bin/activate   # For Mac/Linux
pip install -r requirements.txt


### .env file
```ini
GROQ_API_KEY=your_groq_key
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
```

### Web Interface (QR + Voice Suuported)
```bash
streamlit run app/interfaces/web_ui.py
```

-Scan the generated qr_code.png to open on mobile.
-Mic icon allows speaking instead of typing.
-Logs stored under app/logs/.

### CLI Interface
```bash
python main.py
```
-Use for simple debugging or text-only interaction.
-Automatically logs session to app/logs/.

### Whatsapp Bot via Twilio

#### Step 1: Start Flask server
```bash
python twilio_webhook.py
```

#### Step 2: Expose to Internet
```bash
npx localtunnel --port 5002
```

or

```bash
ngrok http 5002
```
#### Step 3: Set Webhook in Twilio Sandbox

Paste the public URL (e.g., https://xyz.ngrok.io) into the sandbox settings under **"WHEN A MESSAGE COMES IN"** or in the **POST** link box.

## 📁 Logging
Each session creates a log file in app/logs/ as:

```pgsql
session_<timestamp>.json
```

Example log structure:

```json
{
  "channel": "web" | "voice" | "whatsapp",
  "session_id": "abc123",
  "interactions": [
    {
      "timestamp": "2025-07-14T14:32:21Z",
      "user": "Where is the pool?",
      "bot": "The pool is on the 3rd floor, open from 7 AM to 10 PM."
    }
  ]
}
```


## 📊 Admin Dashboard
```bash
streamlit run app/interfaces/admin_dashboard.py
```

### Analytics includes:
- Session counts per channel
- Common intents (if classifier used)
- Timeline of usage
- Export logs (CSV/Excel)


## Rasa Intent Classifier
```bash
rasa train nlu
python app/rasa/intent_classifier.py
```
- Used for intent classification like the following:

```yaml
version: "2.0"
nlu:
- intent: greet
  examples: |
    - hello
    - hi
    - good morning
- intent: goodbye
  examples: |
    - bye
    - see you later
```

## 🎯 Future Work
- Multilingual support (via Hugging Face models)
- Hotel booking integration (via API)
- Concierge scheduling/reservation support
- Docker packaging for cross-platform deployment
- Enhanced analytics: session duration, device info
- Multi-agent support (concierge, booking, manager, etc.)

## 🙋‍♂️ Author

**Atharv Kumar**
📧 atharvkumar43@gmail.com
🔗 https://www.linkedin.com/in/atharv-kumar-270337222/
💻 https://github.com/Machforo

## Acknoewledgements

- LangChain
- Groq Cloud
- Twilio WhatsApp API
- Hugging Face
- Streamlit

