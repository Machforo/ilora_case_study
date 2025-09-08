import logging
import os


LOG_PATH_TXT = 'data\\bot.log'

#-- function to initialize a logger that writes log to a file
def setup_logger(name: str, log_file: str = LOG_PATH_TXT, level=logging.INFO):
    #os.makedirs(log_file, exist_ok=True)

    formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.hasHandlers():
        logger.addHandler(handler)

    return logger

logger = setup_logger("web")

def log_chat(source: str, session_id: str, user_input: str, response: str, intent: str = None, guest_status: str = None):
    # Optional parts
    intent_str = f" | Intent: {intent}" if intent else ""
    guest_str = f" | Guest: {guest_status}" if guest_status else ""

    # Final message
    message = f"{source} | {session_id} | {user_input} | {response}{intent_str}{guest_str}"
    logger.info(message)
