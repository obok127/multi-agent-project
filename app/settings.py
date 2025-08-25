import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
    ADK_MODEL = os.getenv("ADK_MODEL", "gemini-2.0-flash-8b")
    FRONT_ORIGIN = os.getenv("FRONT_ORIGIN", "http://localhost:5173")


settings = Settings()


