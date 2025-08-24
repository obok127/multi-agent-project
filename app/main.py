import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()  # ← .env 로드 (OPENAI_API_KEY/GOOGLE_API_KEY 확실히 잡음)

# 새로운 아키텍처만 사용
from app.chat_service_new import orchestrate
from app.database import get_user_by_name, create_user, update_last_visit, get_chat_sessions_by_user, delete_chat_session
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

class UserNameIn(BaseModel):
    name: str

class ChatIn(BaseModel):
    message: str
    user_name: Optional[str] = None
    session_id: Optional[int] = None

# 새로운 아키텍처 엔드포인트 (메인 엔드포인트로 사용)
@app.post("/chat")
async def chat_endpoint(
    request: Request,
    message: Optional[str] = Form(None),
    session_id: str = Form("default"),
    user_name: str = Form(""),
    images: Optional[List[UploadFile]] = File(None),
    mask: Optional[UploadFile] = File(None),
):
    if message is None:  # JSON 요청도 허용
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id", session_id)
        user_name = body.get("user_name", user_name)

    resp = await orchestrate(
        message=message,
        images=images or [],
        mask=mask,
        session_id=session_id,
        user_name=user_name,
        history=[],  # DB 히스토리 붙일 수 있으면 여기 주입
    )
    return JSONResponse(resp.dict())

@app.post("/chat/api/user/save")
async def save_user(payload: UserNameIn):
    """사용자 정보 저장"""
    try:
        user = get_user_by_name(payload.name)
        if not user:
            user = create_user(payload.name)
        else:
            update_last_visit(payload.name)  # name으로 업데이트
        return {"status": "success", "user_id": user['id']}
    except Exception as e:
        logger.exception("user.save.failed", extra={"name": payload.name})
        raise HTTPException(status_code=500, detail="사용자 저장 실패")

@app.get("/chat/api/chat/sessions/{user_name}")
async def get_user_sessions(user_name: str):
    """사용자별 채팅 세션 조회"""
    try:
        user = get_user_by_name(user_name)
        if not user:
            return {"sessions": []}
        
        sessions = get_chat_sessions_by_user(user['id'])
        return {"sessions": sessions}
    except Exception as e:
        logger.exception("sessions.get.failed", extra={"user_name": user_name})
        raise HTTPException(status_code=500, detail="세션 조회 실패")

@app.delete("/chat/api/chat/sessions/{session_id}")
async def delete_session(session_id: int):
    """채팅 세션 삭제"""
    try:
        delete_chat_session(session_id)
        return {"status": "success"}
    except Exception as e:
        logger.exception("session.delete.failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail="세션 삭제 실패")

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