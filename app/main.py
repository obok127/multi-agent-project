import os
import uuid
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.settings import settings
from typing import List, Optional
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()  # ← .env 로드 (OPENAI_API_KEY/GOOGLE_API_KEY 확실히 잡음)

# 새로운 아키텍처만 사용
from app.orchestrator import orchestrate
from app.database import get_user_by_name, create_user, update_last_visit, get_chat_sessions_by_user, delete_chat_session, get_messages_by_session
import logging

# 새로운 서비스들
from app.session_manager import session_manager
from app.onboarding_service import onboarding_service
from app.error_handler import ChatServiceError, handle_exception

def get_session_id(request: Request, response: Response, session_id: str = None) -> str:
    """세션 ID 관리 - 쿠키 기반"""
    # 1. Form에서 session_id가 있으면 사용
    if session_id:
        sid = session_id
    # 2. 쿠키에서 sid 확인
    elif request.cookies.get("sid"):
        sid = request.cookies.get("sid")
    # 3. 없으면 새로 생성
    else:
        sid = str(uuid.uuid4())
    
    # 최초 1회만 쿠키 설정
    if not request.cookies.get("sid"):
        response.set_cookie("sid", sid, httponly=False, samesite="lax", max_age=86400*30)  # 30일
    
    return sid

logger = logging.getLogger(__name__)

app = FastAPI(title="Mini Carrot", version="1.1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONT_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    response: Response,
    message: Optional[str] = Form(None),
    session_id: str = Form("default"),
    user_name: str = Form(""),
    images: Optional[List[UploadFile]] = File(None),
    mask: Optional[UploadFile] = File(None),
    image_path: Optional[str] = Form(None),
    selection: Optional[UploadFile] = File(None),
):
    if message is None:  # JSON 요청도 허용
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id", session_id)
        user_name = body.get("user_name", user_name)

    # 세션 ID 관리
    sid = get_session_id(request, response, session_id)
    session = session_manager.get_session(sid)
    
    logger.info(f"CHAT_ENDPOINT: sid={sid}, onboarded={session.is_onboarded}, asked_once={session.asked_once}")

    try:
        # 세션 히스토리 가져오기
        history = session_manager.get_history(sid)
        
        resp = await orchestrate(
            message=message,
            images=images or [],
            mask=mask,
            selection=selection,
            image_path_str=image_path,
            session_id=sid,
            user_name=user_name,
            history=history,
            session=session,  # 세션 객체 전달
        )
        payload = resp.model_dump()
        # 세션 식별자 포함(프론트에서 세션 고정/목록 로딩에 사용)
        payload.setdefault("session_id", sid)
        logger.info(f"CHAT_ENDPOINT: response={payload}")
        return JSONResponse(payload)
    except Exception as e:
        error_result = handle_exception(e, "chat_endpoint")
        return JSONResponse(error_result, status_code=500)

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

@app.get("/chat/api/chat/sessions/{session_id}/messages")
async def get_session_messages(session_id: int):
    """특정 세션의 메시지 목록 조회 (사이드바/복원용)"""
    try:
        msgs = get_messages_by_session(session_id) or []
        return {"messages": msgs}
    except Exception as e:
        logger.exception("session.messages.failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail="메시지 조회 실패")

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