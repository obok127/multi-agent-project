import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()  # ← .env 로드 (OPENAI_API_KEY/GOOGLE_API_KEY 확실히 잡음)

from app.routers import chat, agent
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Mini Carrot", version="1.1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# 정적 파일 설정
BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_DIR = os.path.join(STATIC_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

INDEX_PATH = os.path.join(BASE_DIR, "frontend", "index.html")

# 라우터 등록
app.include_router(chat.router)
app.include_router(agent.router)

@app.get("/health")
async def health():
    """헬스 체크 엔드포인트"""
    return {"status": "ok"}

@app.get("/")
async def home():
    """메인 페이지"""
    if not os.path.isfile(INDEX_PATH):
        raise HTTPException(500, f"index.html not found at {INDEX_PATH}")
    return FileResponse(INDEX_PATH, media_type="text/html")