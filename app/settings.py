import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings:
    OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
    ADK_MODEL = os.getenv("ADK_MODEL", "gemini-2.0-flash-8b")
    FRONT_ORIGIN = os.getenv("FRONT_ORIGIN", "http://localhost:5173")
    # Azure OpenAI
    USE_AZURE_OPENAI = os.getenv("USE_AZURE_OPENAI", "false").lower() not in ("0", "false", "no")
    AZURE_OPENAI_API_KEY = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    AZURE_OPENAI_ENDPOINT = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    AZURE_OPENAI_API_VERSION = (os.getenv("AZURE_OPENAI_API_VERSION") or "").strip()
    AZURE_OPENAI_DEPLOYMENT_CHAT = (os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT") or "").strip()
    AZURE_OPENAI_DEPLOYMENT_IMAGE = (os.getenv("AZURE_OPENAI_DEPLOYMENT_IMAGE") or "").strip()


settings = Settings()


