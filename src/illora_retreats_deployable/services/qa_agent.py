# qa_agent.py

from typing import Optional
#from azure.ai.inference import ChatCompletionsClient
#from azure.ai.inference.models import SystemMessage, UserMessage
#from azure.core.credentials import AzureKeyCredential
from langchain_openai import ChatOpenAI
from vector_store import create_vector_store
from config import Config
from logger import setup_logger
import os, json

logger = setup_logger("QAAgent")

class ConciergeBot:
    def __init__(self):
        try:
            # Build / fetch FAISS vector store (cached in-process)
            self.vector_store = create_vector_store()

            # Stronger retrieval: MMR, fetch more then keep top-k
            k = getattr(Config, "RETRIEVER_K", 5)
            fetch_k = getattr(Config, "RETRIEVER_FETCH_K", 20)
            self.retriever = self.vector_store.as_retriever(
                search_type="mmr", search_kwargs={"k": k, "fetch_k": fetch_k}
            )

            # Initialize GitHub Inference via Azure AI Inference SDK
            self.llm = ChatOpenAI(
                api_key=Config.OPENAI_API_KEY,
                model=Config.OPENAI_MODEL,
                base_url=Config.GROQ_API_BASE,
                temperature=0,
            )

            # Load Do’s & Don’ts
            self.dos_donts_path = "data\\dos_donts.json"
            self.dos_donts = self._load_dos_donts()

            logger.info("ILLORA RETREATS QA agent initialized successfully.")

        except Exception as e:
            logger.error(f"Error initializing QA agent: {e}")
            raise

    def _load_dos_donts(self):
        """Load Do's & Don'ts JSON file if available."""
        if not os.path.exists(self.dos_donts_path):
            return []
        try:
            with open(self.dos_donts_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load Do's & Don'ts file: {e}")
            return []

    def _build_prompt(self, hotel_data: str, query: str) -> str:

        '''
        Agent Manager
        '''

        agent_name = 'AI Assistant'

        agents_file = 'data\\agents.json'
        with open(agents_file, 'r') as f_new_1:
            agents = json.load(f_new_1)
        
        for agent in agents:
            if agent['agent_allocation'] == 'Front Desk Concierge':
                agent_name = agent['agent_name']
        
        
        #####################################################
        print("#################################")
        print(agent_name)
        print("##################################")

        """
        Construct the system prompt that combines branding + hotel data + rules.
        """
        rules_text = ""
        if self.dos_donts:
            rules_text = "\n\n📋 **Important Communication Rules:**\n"
            for idx, entry in enumerate(self.dos_donts, start=1):
                do = entry.get("do", "").strip()
                dont = entry.get("dont", "").strip()
                if do:
                    rules_text += f"- ✅ Do: {do}\n"
                if dont:
                    rules_text += f"- ❌ Don't: {dont}\n"

        return (
            f"You are an AI agent named {agent_name} a knowledgeable, polite, and concise concierge assistant at *ILLORA RETREATS*, "
            "a premium hotel known for elegant accommodations, gourmet dining, rejuvenating spa treatments, "
            "a fully-equipped gym, pool access, 24x7 room service, meeting spaces, and personalized hospitality.\n\n"
            "Answer smost almost all of the questions using the Hotel Data below. If the data does not contain the answer you can take it by yourself, but remember **DO NOT MAKE ANY False FACTS** "
            f"Agent Name:\n{agent_name}\n\n"
            f"Hotel Data:\n{hotel_data}\n\n"
            f"Guest Query: {query}\n"
            f"{rules_text}"
        )

    def ask(self, query: str, user_type: Optional[str] = None) -> str:
        try:
            restricted_services = [
                "wake-up call", "spa", "gym", "pool", "room service", "book a room", "booking"
            ]
            lower_query = (query or "").lower()

            # Block restricted queries for non-guests
            if user_type == "non-guest" and any(term in lower_query for term in restricted_services):
                return (
                    "We're sorry, this service is exclusive to *guests* at ILLORA RETREATS.\n"
                    "Feel free to explore our dining options, events, and lobby amenities!"
                )

            # 🔑 Correct: retrieve using raw query only
            docs = self.retriever.invoke(query)
            hotel_data = "\n\n".join(d.page_content for d in docs) if docs else ""

            # Build system prompt with rules
            system_prompt = self._build_prompt(hotel_data, query)
            print(system_prompt)

            # Call the LLM directly
            response = self.llm.invoke(system_prompt)
            print(response)

            final_answer = response.content.strip() if hasattr(response, "content") else str(response)

            logger.info(f"Processed query at ILLORA RETREATS: {query}")
            return final_answer or "I'm here to help with any questions about ILLORA RETREATS."

        except Exception as e:
            print(f"Error processing query at ILLORA RETREATS '{query}': {e}")
            logger.error(f"Error processing query at ILLORA RETREATS '{query}': {e}")
            return (
                "We're sorry, there was an issue while assisting you. "
                "Please feel free to ask again or contact the ILLORA RETREATS front desk for immediate help."
            )
        

