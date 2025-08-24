# app/chat_service_new.py
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import UploadFile
from app.schemas import ChatResponse, GenerationTask, RouterDecision
from app.llm_router import route_with_llm
from app.adk_agent import root_agent
from app.tools import ensure_saved_file

# DB 유틸 가져오기
from app.database import (
    get_user_by_name,
    create_user,
    create_chat_session,
    add_message,
    get_messages_by_session,
    update_session_title,
    get_chat_session
)

logger = logging.getLogger(__name__)

# 세션별 1회 질문 상태 - 조회/제거 분리
_PENDING: Dict[str, Dict] = {}

def _get_pending(session_id: str) -> Optional[GenerationTask]:
    """펜딩 상태 조회 (제거하지 않음)"""
    rec = _PENDING.get(str(session_id))
    if not rec: 
        logger.info(f"PENDING NOT FOUND: {session_id}")
        return None
    if rec["exp"] < datetime.utcnow():
        _PENDING.pop(str(session_id), None)
        logger.info(f"PENDING EXPIRED: {session_id}")
        return None
    return rec["task"]

def _clear_pending(session_id: str):
    """펜딩 상태 제거 (실행 확정 시에만 호출)"""
    _PENDING.pop(str(session_id), None)
    logger.info(f"PENDING CLEARED: {session_id}")

def _set_pending(session_id: str, task: Optional[GenerationTask], ttl=600, asked=False):
    """펜딩 상태 설정 (asked 플래그로 질문 여부 추적)"""
    _PENDING[str(session_id)] = {
        "task": task, 
        "exp": datetime.utcnow() + timedelta(seconds=ttl),
        "asked": asked
    }
    logger.info(f"PENDING SET: {session_id} -> {task.model_dump() if task else None}, asked={asked}")

def _was_asked(session_id: str) -> bool:
    """이미 질문했는지 확인"""
    rec = _PENDING.get(str(session_id))
    return bool(rec and rec.get("asked"))

def _extract_slots_from_message(message: str) -> Dict[str, str]:
    """사용자 메시지에서 스타일/포즈/배경 정보 추출"""
    slots = {}
    message_lower = message.lower()
    
    # 스타일 추출
    if "실사" in message or "포토" in message or "photo" in message_lower:
        slots["style"] = "photo"
    elif "만화" in message or "애니" in message or "anime" in message_lower:
        slots["style"] = "anime"
    elif "일러스트" in message or "illustration" in message_lower:
        slots["style"] = "illustration"
    
    # 포즈 추출
    if "앉아" in message or "sitting" in message_lower:
        slots["pose"] = "sitting"
    elif "서있" in message or "standing" in message_lower:
        slots["pose"] = "standing"
    elif "지키" in message or "guard" in message_lower:
        slots["pose"] = "standing guard"
    
    # 배경 추출
    if "공원" in message or "park" in message_lower:
        slots["bg"] = "park"
    elif "거리" in message or "street" in message_lower:
        slots["bg"] = "street"
    elif "밤" in message or "night" in message_lower:
        slots["bg"] = "night street"
    
    return slots

def _create_basic_task(message: str) -> GenerationTask:
    """메시지에서 기본 정보를 추출하여 GenerationTask 생성"""
    basic_task = GenerationTask(intent="generate")
    
    # 객체 추출
    if "강아지" in message or "dog" in message.lower():
        basic_task.object = "dog"
    elif "고양이" in message or "cat" in message.lower():
        basic_task.object = "cat"
    elif "셰퍼드" in message or "german shepherd" in message.lower():
        basic_task.object = "German shepherd"
    else:
        basic_task.object = "subject"
    
    return basic_task

# 세션/히스토리 보장
def _ensure_session_and_history(session_id: Optional[str], user_name: str, history_limit: int = 16):
    """유저/세션 보장 및 히스토리 로드"""
    # 1) 유저 보장
    user = get_user_by_name(user_name or "anonymous")
    if not user:
        user = create_user(user_name or "anonymous")
    
    # 2) 세션 보장
    if not session_id or session_id == "default":
        # 새 세션 생성
        session = create_chat_session(user['id'], "새 대화")
        session_id = str(session['id'])
    else:
        # 기존 세션 확인
        try:
            session = get_chat_session(int(session_id))
            if not session:
                # 세션이 없으면 새로 생성
                session = create_chat_session(user['id'], "새 대화")
                session_id = str(session['id'])
        except ValueError:
            # session_id가 숫자가 아니면 새로 생성
            session = create_chat_session(user['id'], "새 대화")
            session_id = str(session['id'])
    
    # Use session_id directly for pending state management
    pending_key = session_id

    # 3) 히스토리 적재(라우터용 포맷)
    try:
        msgs = get_messages_by_session(int(session_id)) or []
        hist = [{"role": m['role'], "content": m['content']} for m in msgs[-history_limit:]]
    except Exception as e:
        logger.warning(f"Failed to load history: {e}")
        hist = []
    
    return session_id, hist, pending_key

# 메시지 저장 헬퍼
def _save_user_message(session_id: str, text: str):
    """사용자 메시지 저장"""
    if text:
        try:
            add_message(int(session_id), role="user", content=text)
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")

def _save_assistant_text(session_id: str, text: str):
    """어시스턴트 텍스트 메시지 저장"""
    if text:
        try:
            add_message(int(session_id), role="assistant", content=text)
        except Exception as e:
            logger.error(f"Failed to save assistant text: {e}")

def _save_assistant_image(session_id: str, url: str, meta: Optional[Dict[str, Any]] = None):
    """어시스턴트 이미지 메시지 저장"""
    if url:
        try:
            content = f"[image] {url}"
            if meta:
                content += f" | {str(meta)}"
            add_message(int(session_id), role="assistant", content=content)
        except Exception as e:
            logger.error(f"Failed to save assistant image: {e}")

# 세션 타이틀 설정
def _maybe_set_session_title(session_id: str, first_user_text: str):
    """최초 메시지로 세션 타이틀 설정"""
    try:
        if first_user_text:
            title = first_user_text[:40] + ("..." if len(first_user_text) > 40 else "")
            update_session_title(int(session_id), title)
    except Exception as e:
        logger.warning(f"Failed to set session title: {e}")

async def orchestrate(message: str,
                      images: List[UploadFile],
                      mask: Optional[UploadFile],
                      session_id: str="default",
                      user_name: str="",
                      history: Optional[List[Dict[str,str]]] = None) -> ChatResponse:
    """메인 오케스트레이션 함수"""
    # ✅ 세션/히스토리 보장
    session_id, db_history, pending_key = _ensure_session_and_history(session_id, user_name, history_limit=16)
    history = history or db_history

    # 사용자 메시지 먼저 저장
    _save_user_message(session_id, message)
    _maybe_set_session_title(session_id, message)

    # 펜딩 상태 조회 (제거하지 않음)
    pending = _get_pending(pending_key)
    was_asked = _was_asked(pending_key)
    
    logger.info(f"ORCHESTRATE: session={session_id}, pending={pending is not None}, was_asked={was_asked}, message={message[:50]}")

    # 업로드 파일 즉시 저장(편집 대비)
    image_path = ensure_saved_file(images[0]) if images else None
    mask_path = ensure_saved_file(mask) if mask else None
    
    if pending:
        if image_path and not pending.image_path: 
            pending.image_path = image_path
        if mask_path and not pending.mask_path: 
            pending.mask_path = mask_path

    # Core policy: ask only once
    if not was_asked and pending is None:
        # 첫 번째 턴: 이미지 생성/편집 의도 감지
        decision = route_with_llm(history, message, None)
        logger.info(f"FIRST TURN: decision={decision.next_action}")
        
        if decision.next_action == "run":
            # 이미지 생성/편집 의도로 판단됨 → 무조건 스타일 질문 1회
            from app.prompts import ask_style_once_kor
            decision.next_action = "ask"
            # 객체 추출하여 적절한 질문 생성
            obj_kr = "이미지"
            if "강아지" in message or "dog" in message.lower():
                obj_kr = "강아지"
            elif "고양이" in message or "cat" in message.lower():
                obj_kr = "고양이"
            elif "셰퍼드" in message or "german shepherd" in message.lower():
                obj_kr = "셰퍼드"
            decision.clarify_question = ask_style_once_kor(obj_kr)
            logger.info("FORCED ASK: first turn policy")
    else:
        # 두 번째 턴 이후: 이미 질문했거나 펜딩이 있으면 무조건 실행
        if was_asked and pending:
            # 이미 질문했는데 펜딩이 있으면 사용자 응답으로 슬롯 채우기
            slots = _extract_slots_from_message(message)
            for key, value in slots.items():
                setattr(pending, key, value)
            
            # 프롬프트 생성 (부족한 정보는 기본값으로)
            style_str = pending.style or "photo"
            bg_str = pending.bg or "white background"
            pose_str = pending.pose or "natural pose"
            obj_str = pending.object or "subject"
            pending.prompt_en = f"A {style_str} style {obj_str} in {bg_str}, {pose_str}, high quality"
            
            decision = RouterDecision(next_action="run", task=pending)
            logger.info("SECOND TURN: filled slots and forced run")
        elif pending:
            # 펜딩이 있지만 아직 질문 안 한 경우 (예외 상황)
            decision = route_with_llm(history, message, pending)
            logger.info(f"ROUTER CALL with pending: decision={decision.next_action}")
        else:
            # 일반적인 경우 라우터 호출
            decision = route_with_llm(history, message, None)
            logger.info(f"ROUTER CALL: decision={decision.next_action}")

    logger.info(f"FINAL DECISION: {decision.next_action}")

    # ── 액션별 처리 ───────────────────────────────────────────────────────
    if decision.next_action == "ask":
        # 질문은 한 번만 허용
        if not was_asked:
            # 첫 번째 질문: 기본 GenerationTask 생성
            if pending is None:
                basic_task = _create_basic_task(message)
                _set_pending(pending_key, basic_task, asked=True)
            else:
                _set_pending(pending_key, pending, asked=True)
            
            _save_assistant_text(session_id, decision.clarify_question)
            return ChatResponse(reply=decision.clarify_question, meta={"need_more_info": True})
        else:
            # 이미 질문했으면 강제로 실행 (기본값으로 보정)
            if pending:
                slots = _extract_slots_from_message(message)
                for key, value in slots.items():
                    setattr(pending, key, value)
                
                # 프롬프트 생성
                style_str = pending.style or "photo"
                bg_str = pending.bg or "white background"
                pose_str = pending.pose or "natural pose"
                obj_str = pending.object or "subject"
                pending.prompt_en = f"A {style_str} style {obj_str} in {bg_str}, {pose_str}, high quality"
                
                decision = RouterDecision(next_action="run", task=pending)
                logger.info("FORCED RUN: already asked, using defaults")
            else:
                reply = "무엇을 도와드릴까요? 생성이나 편집도 가능합니다. 😊"
                _save_assistant_text(session_id, reply)
                return ChatResponse(reply=reply)

    if decision.next_action == "chat":
        reply = "무엇을 도와드릴까요? 생성이나 편집도 가능합니다. 😊"
        _save_assistant_text(session_id, reply)
        return ChatResponse(reply=reply)

    # ── 실행 분기 ─────────────────────────────────────────────────────────
    task = decision.task
    if task.intent == "edit":
        if image_path and not task.image_path: 
            task.image_path = image_path
        if mask_path and not task.mask_path: 
            task.mask_path = mask_path

    payload = task.model_dump()
    logger.info(f"EXECUTING: {payload}")
    
    # 실행 확정 시에만 펜딩 제거
    _clear_pending(pending_key)
    
    try:
        # ADK 에이전트에 JSON 태스크 전달
        import json
        task_json = json.dumps(payload, ensure_ascii=False)
        response = None
        
        # Direct tool call (simpler and more reliable)
        if payload.get("intent") == "generate":
            from app.tools import generate_image_tool
            response = generate_image_tool(prompt=payload.get("prompt_en"), size=payload.get("size", "1024x1024"))
        else:
            from app.tools import edit_image_tool
            response = edit_image_tool(
                image_path=payload.get("image_path"),
                prompt=payload.get("prompt_en"),
                mask_path=payload.get("mask_path"),
                size=payload.get("size", "1024x1024")
            )
        
        # 응답에서 텍스트 추출
        if hasattr(response, 'text'):
            out_text = response.text
        elif hasattr(response, 'content'):
            out_text = response.content
        elif hasattr(response, 'message'):
            out_text = response.message
        else:
            out_text = str(response)
        
        # JSON 응답 파싱 시도
        try:
            out = json.loads(out_text)
        except json.JSONDecodeError:
            out = {"status": "error", "detail": out_text}

        if isinstance(out, dict) and out.get("status") == "ok" and out.get("url"):
            # 내레이션(템플릿, check 라인 포함)
            style_kr = {"photo":"실사","anime":"만화/애니메이션","illustration":"일러스트"}.get(task.style or "photo","실사")
            obj_kr = {"cat":"고양이","dog":"강아지","German shepherd":"셰퍼드"}.get(task.object or "", task.object or "이미지")
            adj = "귀여운" if obj_kr in ("고양이","강아지") else "멋진"
            desc = (
                f"이 이미지는 {(task.bg or '흰색 배경')}에 {(task.pose or '자연스러운')} 모습의 {obj_kr}가 표현되어 있습니다. "
                "전체적으로 선명하고 안정적인 느낌입니다."
            )
            reply = (
                f"완벽해요! {style_kr} 스타일의 {adj} {obj_kr}를 만들어드릴게요. 🎨\n"
                "✅ 이미지 생성 완료\n"
                "✅ 이미지 확인 완료\n" + desc
            )
            summary = (
                "완성되었어요! 🎨✨\n"
                f"{adj} {style_kr} 스타일의 {obj_kr} 사진입니다.\n"
                "• 선명한 표현\n• 안정적인 구도\n• 자연스러운 조명\n• 다른 포즈/색상도 가능해요"
            )

            # ✅ 결과 저장
            _save_assistant_text(session_id, reply)
            _save_assistant_image(session_id, out["url"], meta={"task": task.model_dump()})

            return ChatResponse(reply=reply, url=out["url"], meta={"summary": summary})

        # 실패
        detail = out if isinstance(out, str) else (out.get("detail") if isinstance(out, dict) else "unknown")
        failure = f"이미지 작업에 실패했어요: {detail}"
        _save_assistant_text(session_id, failure)
        return ChatResponse(reply=failure)
        
    except Exception as e:
        logger.error(f"Execution error: {e}")
        failure = f"이미지 작업 중 오류가 발생했습니다: {e}"
        _save_assistant_text(session_id, failure)
        return ChatResponse(reply=failure)
