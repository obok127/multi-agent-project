from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.services.image_request import ImageRequestInfo, extract_image_request_info_from_history
from app.intents import detect_intent, Intent
from app.tools import generate_image_tool
from app.database import (
    get_user_by_name, create_user, update_last_visit,
    create_chat_session, get_chat_sessions_by_user, get_chat_session,
    add_message, get_messages_by_session, update_session_title,
    delete_chat_session
)
from app.prompts import CHAT_SYSTEM_PROMPT
from app.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatIn(BaseModel):
    message: str
    user_name: Optional[str] = None
    session_id: Optional[int] = None
    image_path: Optional[str] = None

class UserNameIn(BaseModel):
    name: str

class ChatSessionIn(BaseModel):
    user_name: str
    title: str

class MessageIn(BaseModel):
    session_id: int
    role: str
    content: str

@router.post("/")
async def chat_endpoint(
    message: str = Form(...),
    user_name: Optional[str] = Form(None),
    session_id: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None)
):
    """채팅 메시지 처리 엔드포인트 (이미지 업로드 지원)"""
    # ChatIn 객체 생성
    payload = ChatIn(
        message=message,
        user_name=user_name,
        session_id=session_id
    )
    
    # 이미지가 있으면 임시 저장하고 경로를 payload에 추가
    if image:
        import os
        import uuid
        from pathlib import Path
        
        # 업로드 디렉토리 생성
        upload_dir = Path("app/static/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # 파일 저장
        file_extension = Path(image.filename).suffix if image.filename else ".jpg"
        filename = f"{uuid.uuid4().hex}{file_extension}"
        file_path = upload_dir / filename
        
        with open(file_path, "wb") as buffer:
            content = await image.read()
            buffer.write(content)
        
        # payload에 이미지 경로 추가
        payload.image_path = str(file_path)
        logger.info("image.uploaded", extra={
            "filename": filename,
            "size": len(content),
            "user_message": message[:50]
        })
    
    return await ChatService.process_message(payload)

@router.post("/api/user/save")
async def save_user(payload: UserNameIn):
    """사용자 정보 저장"""
    try:
        user = get_user_by_name(payload.name)
        if not user:
            user = create_user(payload.name)
        else:
            update_last_visit(user['id'])
        return {"status": "success", "user_id": user['id']}
    except Exception as e:
        logger.exception("user.save.failed", extra={"name": payload.name})
        raise HTTPException(status_code=500, detail="사용자 저장 실패")

@router.get("/api/chat/sessions/{user_name}")
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

@router.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: int):
    """채팅 세션 삭제"""
    try:
        delete_chat_session(session_id)
        return {"status": "success"}
    except Exception as e:
        logger.exception("session.delete.failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail="세션 삭제 실패")

@router.post("/generate-image")
async def generate_image_endpoint(payload: ChatIn):
    """이미지 생성 전용 엔드포인트"""
    try:
        from app.chat_service import ChatService
        return await ChatService._handle_image_generation(
            payload.message, 
            [],  # 빈 히스토리 (이미지 생성만)
            "이미지를 생성하고 있습니다...", 
            payload.session_id, 
            type('IntentResult', (), {'label': Intent.IMAGE_GENERATE})(), 
            None
        )
    except Exception as e:
        logger.exception("image.generate.failed", extra={"user_message": payload.message})
        raise HTTPException(status_code=500, detail="이미지 생성 실패")
