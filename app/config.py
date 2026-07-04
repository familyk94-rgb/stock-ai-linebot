import os
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
FINMIND_API_TOKEN = os.getenv("FINMIND_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")