import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
DATABASE_PATH = os.path.join(BASE_DIR, "messages.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Путь к картинке инструкции (файл должен лежать в корне проекта)
INSTRUCTION_IMAGE_PATH = os.path.join(BASE_DIR, "instruction.jpg")