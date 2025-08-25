# app/orchestrator.py
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import UploadFile
from app.schemas import ChatResponse, GenerationTask, RouterDecision
from app.router import route_with_llm
from app.adk import root_agent
from app.tools import ensure_saved_file

# 온보딩 모듈 가져오기
from app.onboarding_service import onboarding_service

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



def _extract_slots_from_message(message: str) -> Dict[str, str]:
    """사용자 메시지에서 스타일/포즈/배경 정보 추출"""
    slots = {}
    message_lower = message.lower()
    
    # "몰라", "모르겠어" 등의 응답 처리
    if any(keyword in message_lower for keyword in ["몰라", "모르", "상관없", "아무", "랜덤", "그냥", "대충"]):
        # 기본값으로 설정
        slots["style"] = "photo"  # 기본 스타일
        slots["pose"] = "sitting"  # 기본 포즈
        slots["bg"] = "white background"  # 기본 배경
        return slots
    
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

def _fill_defaults(task: GenerationTask, user_msg: str = "") -> GenerationTask:
    """부족한 슬롯을 기본값으로 채우기"""
    # 필수 슬롯: object (존재해야 함)
    if not task.object:
        # 객체 추출 시도
        if "강아지" in user_msg or "dog" in user_msg.lower():
            task.object = "dog"
        elif "고양이" in user_msg or "cat" in user_msg.lower():
            task.object = "cat"
        elif "셰퍼드" in user_msg or "german shepherd" in user_msg.lower():
            task.object = "German shepherd"
        else:
            task.object = "cute character"  # 기본값
    
    # 선택 슬롯들 (없으면 기본값)
    if not task.style:
        task.style = "photo"  # 기본 스타일
    
    if not task.pose:
        task.pose = "standing"  # 기본 포즈
    
    if not task.bg:
        task.bg = "plain white"  # 기본 배경
    
    if not task.mood:
        task.mood = "cute"  # 기본 분위기
    
    return task

def _has_minimum_fields(task: GenerationTask) -> bool:
    """최소 필수 필드가 있는지 확인"""
    return bool(task.object and task.intent in ["generate", "edit"])

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
    
    # 3) 히스토리 적재(라우터용 포맷)
    try:
        msgs = get_messages_by_session(int(session_id)) or []
        hist = [{"role": m['role'], "content": m['content']} for m in msgs[-history_limit:]]
    except Exception as e:
        logger.warning(f"Failed to load history: {e}")
        hist = []
    
    return session_id, hist

# 메시지 저장 헬퍼
def _save_user_message(session_id: str, text: str):
    """사용자 메시지 저장"""
    if text:
        try:
            # session_id가 문자열이면 정수로 변환
            session_id_int = int(session_id) if isinstance(session_id, str) else session_id
            add_message(session_id_int, role="user", content=text)
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")

def _save_assistant_text(session_id: str, text: str):
    """어시스턴트 텍스트 메시지 저장"""
    if text:
        try:
            # session_id가 문자열이면 정수로 변환
            session_id_int = int(session_id) if isinstance(session_id, str) else session_id
            add_message(session_id_int, role="assistant", content=text)
        except Exception as e:
            logger.error(f"Failed to save assistant text: {e}")

def _save_assistant_image(session_id: str, url: str, meta: Optional[Dict[str, Any]] = None):
    """어시스턴트 이미지 메시지 저장"""
    if url:
        try:
            content = f"[image] {url}"
            if meta:
                content += f" | {str(meta)}"
            # session_id가 문자열이면 정수로 변환
            session_id_int = int(session_id) if isinstance(session_id, str) else session_id
            add_message(session_id_int, role="assistant", content=content)
        except Exception as e:
            logger.error(f"Failed to save assistant image: {e}")

# 세션 타이틀 설정
def _maybe_set_session_title(session_id: str, first_user_text: str):
    """최초 메시지로 세션 타이틀 설정"""
    try:
        if first_user_text:
            title = first_user_text[:40] + ("..." if len(first_user_text) > 40 else "")
            # session_id가 문자열이면 정수로 변환
            session_id_int = int(session_id) if isinstance(session_id, str) else session_id
            update_session_title(session_id_int, title)
    except Exception as e:
        logger.warning(f"Failed to set session title: {e}")

async def orchestrate(message: str,
                      images: List[UploadFile],
                      mask: Optional[UploadFile],
                      session_id: str="default",
                      user_name: str="",
                      history: Optional[List[Dict[str,str]]] = None,
                      session=None) -> ChatResponse:
    """메인 오케스트레이션 함수"""
    # ✅ 세션/히스토리 보장 (사용자 이름이 있으면 세션 ID를 사용자 기반으로 고정)
    if user_name.strip():
        # 사용자 이름이 있으면 해당 사용자의 세션을 찾거나 생성
        from app.database import get_user_by_name, get_chat_sessions_by_user, create_chat_session
        user = get_user_by_name(user_name.strip())
        if user:
            sessions = get_chat_sessions_by_user(user['id'])
            if sessions:
                # 기존 세션 사용
                session_id = str(sessions[0]['id'])
            else:
                # 새 세션 생성
                session = create_chat_session(user['id'], f"{user_name}님과의 대화")
                session_id = str(session['id'])
        else:
            # 새 사용자 생성
            from app.database import create_user
            user = create_user(user_name.strip())
            session = create_chat_session(user['id'], f"{user_name}님과의 대화")
            session_id = str(session['id'])
    else:
        # 사용자 이름이 없으면 기존 로직 사용
        pass
    
    session_id, db_history = _ensure_session_and_history(session_id, user_name, history_limit=16)
    history = history or db_history
    
    # 온보딩: 작업을 가로막지 않도록 '지연' 처리. 단, 사용자가 이름을 말하면 즉시 처리
    defer_greet = False
    if session and not session.is_onboarded:
        from app.onboarding_service import onboarding_service
        # 사용자가 이름을 직접 말했으면 즉시 온보딩 완료
        try:
            extracted = onboarding_service.extract_user_name(message)
        except Exception:
            extracted = None
        if extracted:
            onboarding_response, is_onboarding = onboarding_service.handle_onboarding(message, session)
            if onboarding_response:
                return ChatResponse(reply=onboarding_response, meta={"onboarding": is_onboarding})
        else:
            # 이름을 아직 모르면, 이번 턴 작업 수행 후 가벼운 권유를 덧붙이기 위해 지연 플래그만 설정
            defer_greet = True

    # 사용자 메시지 먼저 저장
    _save_user_message(session_id, message)
    _maybe_set_session_title(session_id, message)

    # 펜딩 상태 조회 (세션 객체 기준)
    pending = session.pending_task if session else None
    was_asked = session.asked_once if session else False
    
    logger.info(f"ORCHESTRATE: session={session_id}, pending={pending is not None}, was_asked={was_asked}, message={message[:50]}")

    # 업로드 파일 즉시 저장(편집 대비)
    image_path = ensure_saved_file(images[0]) if images else None
    mask_path = ensure_saved_file(mask) if mask else None
    
    if pending:
        if image_path and not pending.image_path: 
            pending.image_path = image_path
        if mask_path and not pending.mask_path: 
            pending.mask_path = mask_path

    # Core policy: Fast-path (충분 정보면 바로 실행) + Clarify 1회 (불충분시에만)
    if not was_asked and pending is None:
        # 첫 번째 턴: 이미지 생성/편집 의도 감지
        logger.info(f"ROUTER CALL: message='{message}', history_len={len(history)}")
        decision = route_with_llm(history, message, None)
        logger.info(f"FIRST TURN: decision={decision.next_action}, clarify_question={decision.clarify_question[:50] if decision.clarify_question else 'None'}")
        
        if decision.next_action == "run":
            # 충분 정보가 있으면 바로 실행 (질문 생략)
            logger.info("FAST-PATH: 충분 정보로 바로 실행")
        elif decision.next_action == "ask":
            # 불충분 정보 → 1회 질문만
            logger.info(f"CLARIFY 1회: {decision.clarify_question[:50] if decision.clarify_question else 'None'}")
        elif decision.next_action == "chat":
            logger.info("ROUTER CHAT: general conversation")
    else:
        # 두 번째 턴 이후: 의도 유지 여부 확인 후 실행
        if was_asked and pending:
            # 이미 질문했는데 펜딩이 있으면 의도 유지 여부 확인
            decision = route_with_llm(history, message, pending)
            logger.info(f"SECOND TURN: decision={decision.next_action}")
            
            if decision.next_action == "run":
                # 의도 유지 → 기본값 채워서 실행
                slots = _extract_slots_from_message(message)
                for key, value in slots.items():
                    setattr(pending, key, value)
                
                # 프롬프트 생성 (부족한 정보는 기본값으로)
                style_str = pending.style or "photo"
                bg_str = pending.bg or "white background"
                pose_str = pending.pose or "natural pose"
                obj_str = pending.object or "subject"
                pending.prompt_en = f"A {style_str} style {obj_str} in {bg_str}, {pose_str}, high quality"
                
                logger.info("SECOND TURN: 의도 유지, 기본값으로 실행")
            elif decision.next_action == "chat":
                # 의도 변경 → 대화 전환
                if session:
                    session.clear_pending_task()
                logger.info("SECOND TURN: 의도 변경, 대화 전환")
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
                session.set_pending_task(basic_task)
            else:
                session.set_pending_task(pending)
            
            # prompts.py의 프롬프트를 사용하여 질문 생성
            from app.prompts import CHAT_SYSTEM_PROMPT
            from openai import OpenAI
            import os
            
            openai_key = os.getenv("OPENAI_API_KEY")
            if not openai_key:
                raise ValueError("OPENAI_API_KEY not found in environment variables")
            client = OpenAI(api_key=openai_key)
            
            try:
                # 객체와 형용사 추출
                obj_kr = "이미지"
                adj = "귀여운"
                
                if "강아지" in message or "dog" in message.lower():
                    obj_kr = "강아지"
                elif "고양이" in message or "cat" in message.lower():
                    obj_kr = "고양이"
                elif "셰퍼드" in message or "german shepherd" in message.lower():
                    obj_kr = "셰퍼드"
                    adj = "멋진"
                elif "차" in message or "car" in message.lower():
                    obj_kr = "자동차"
                    adj = "멋진"
                elif "풍경" in message or "landscape" in message.lower():
                    obj_kr = "풍경"
                    adj = "아름다운"
                
                # prompts.py의 객체 생성 의도 감지 프롬프트 사용
                system_prompt = CHAT_SYSTEM_PROMPT + f"\n\n현재 상황: 사용자가 '{message}'라고 요청했습니다. 객체는 '{obj_kr}'이고 형용사는 '{adj}'입니다."
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"{adj} {obj_kr} 사진을 만들어주세요"}
                    ],
                    temperature=0.7,
                    max_tokens=300
                )
                clarify_question = response.choices[0].message.content
            except Exception as e:
                logger.error(f"LLM question generation error: {e}")
                # 폴백: prompts.py의 ask_style_once_kor 함수 사용
                from app.prompts import ask_style_once_kor
                clarify_question = ask_style_once_kor(obj_kr)
            
            _save_assistant_text(session_id, clarify_question)
            return ChatResponse(reply=clarify_question, meta={"need_more_info": True})
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
                from app.prompts import get_general_chat_response
                reply = get_general_chat_response(user_name)
                _save_assistant_text(session_id, reply)
                return ChatResponse(reply=reply)

    if decision.next_action == "chat":
        # prompts.py의 프롬프트 사용
        from app.prompts import CHAT_SYSTEM_PROMPT
        from openai import OpenAI
        import os
        
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        client = OpenAI(api_key=openai_key)
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                    {"role": "user", "content": message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            reply = response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            reply = "죄송해요, 잠시 문제가 발생했어요. 다시 시도해주세요."
        
        _save_assistant_text(session_id, reply)
        return ChatResponse(reply=reply)

    # ── 실행 분기 ─────────────────────────────────────────────────────────
    task = decision.task
    
    # 안전장치: 최소 필드 확인
    if not _has_minimum_fields(task):
        task = _fill_defaults(task, message)
        logger.warning(f"MINIMUM FIELDS MISSING: filled defaults for {task.object}")
    
    if task.intent == "edit":
        if image_path and not task.image_path: 
            task.image_path = image_path
        if mask_path and not task.mask_path: 
            task.mask_path = mask_path

    payload = task.model_dump()
    logger.info(f"EXECUTING: {payload}")
    
    # 실행 확정 시에만 펜딩 제거
    if session:
        session.clear_pending_task()
    
    try:
        # ADK 에이전트에 JSON 태스크 전달
        import json
        task_json = json.dumps(payload, ensure_ascii=False)
        response = None
        
        # Direct tool call (현재 경로). 프롬프트 가드 추가.
        raw_prompt = payload.get("prompt_en") or payload.get("prompt") or payload.get("prompt_kr")
        if not raw_prompt or not str(raw_prompt).strip():
            raise ValueError("이미지 프롬프트가 비어 있습니다.")
        if payload.get("intent") == "generate":
            from app.tools import generate_image_tool
            response = generate_image_tool(prompt=raw_prompt, size=payload.get("size", "1024x1024"))
        else:
            from app.tools import edit_image_tool
            response = edit_image_tool(
                image_path=payload.get("image_path"),
                prompt=raw_prompt,
                mask_path=payload.get("mask_path"),
                size=payload.get("size", "1024x1024")
            )
        
        # 응답 표준화
        if isinstance(response, dict):
            out = response
        else:
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
            except Exception:
                out = {"status": "error", "detail": out_text}

        if isinstance(out, dict) and out.get("status") == "ok" and out.get("url"):
            # prompts 기반 내레이션/요약 렌더링
            from app.prompts import render_image_result
            rendered = render_image_result(task)
            reply = rendered["reply"]
            summary = rendered["summary"]

            # 온보딩 미완료 시, 결과 뒤에 가벼운 이름 요청을 덧붙임(지연 온보딩)
            if defer_greet and session and not session.is_onboarded:
                reply = reply + "\n\n(참, 더 개인화해서 도와드리려면 성함도 알려주실래요? 😊)"

            # ✅ 결과 저장
            _save_assistant_text(session_id, reply)
            _save_assistant_image(session_id, out["url"], meta={"task": task.model_dump()})

            return ChatResponse(reply=reply, url=out["url"], meta={"summary": summary})

        # 실패 처리
        detail = out if isinstance(out, str) else (out.get("detail") if isinstance(out, dict) else "unknown")
        
        from app.error_handler import ImageGenerationError
        raise ImageGenerationError(f"이미지 작업에 실패했습니다: {detail}")
        
    except Exception as e:
        logger.error(f"Execution error: {e}")
        from app.error_handler import ImageGenerationError
        raise ImageGenerationError(f"이미지 작업 중 오류가 발생했습니다: {str(e)}")
