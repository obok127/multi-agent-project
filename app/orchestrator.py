# app/orchestrator.py
import logging
import re
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import UploadFile
from app.schemas import ChatResponse, GenerationTask, RouterDecision
from app.router import route_with_llm
from app.adk import root_agent
from app.tools import ensure_saved_file
from app.tools import edit_image_tool, generate_image_tool

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
    get_chat_session,
    get_chat_sessions_by_user,
)

logger = logging.getLogger(__name__)
def _save_assistant_text_dedup(session_id: str, text: str):
    """어시스턴트 텍스트 저장 시 직전 동일 메시지면 중복 저장 방지."""
    if not text:
        return
    try:
        sid = int(session_id) if isinstance(session_id, str) else session_id
        msgs = get_messages_by_session(sid) or []
        if msgs:
            last = msgs[-1]
            if last.get('role') == 'assistant' and (last.get('content') or '').strip() == text.strip():
                return
        add_message(sid, role="assistant", content=text)
    except Exception as e:
        logger.error(f"Failed to save assistant text (dedup): {e}")



def _extract_slots_from_message(message: str) -> Dict[str, str]:
    """사용자 메시지에서 스타일/포즈/배경 정보 추출"""
    slots = {}
    message_lower = message.lower()
    
    # "몰라", "모르겠어" 등의 응답 처리
    if any(keyword in message_lower for keyword in ["몰라", "모르", "상관없", "아무", "랜덤", "그냥", "대충"]):
        # 기본값으로 설정
        slots["style"] = "illustration"  # 기본 스타일(일러스트)
        slots["pose"] = "sitting"  # 기본 포즈
        slots["bg"] = "white background"  # 기본 배경
        slots["mood"] = "cute"  # 기본 분위기(귀엽고 따뜻한 톤 유도)
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

# ---- Edit (user image) helpers -------------------------------------------------
def _build_edit_spec(user_text: str) -> Dict[str, Any]:
    """LLM으로 사용자 설명을 JSON 스펙으로 구조화한다(하드코딩 회피)."""
    try:
        from openai import OpenAI
        import os, json
        from app.prompts import EDIT_SPEC_SYSTEM
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("no_openai_key")
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content": EDIT_SPEC_SYSTEM},
                {"role":"user","content": user_text or ""}
            ],
            temperature=0.2,
            max_tokens=280,
            response_format={"type":"json_object"}
        )
        content = r.choices[0].message.content
        data = json.loads(content)
        # 수비적 보정
        spec = data.get("spec") or {}
        spec.setdefault("keep", ["캐릭터 스타일","선 두께","구도","조명"])
        spec.setdefault("region", "selection")
        missing = data.get("missing") or []
        question = data.get("question") or ""
        return {"spec": spec, "missing": missing, "question": question}
    except Exception:
        # 키가 없거나 실패 시 가장 보수적인 기본값
        return {
            "spec": {
                "subject": None,
                "operations": [],
                "style": None,
                "pose": None,
                "background": None,
                "mood": None,
                "colors": None,
                "region": "selection",
                "keep": ["캐릭터 스타일","선 두께","구도","조명"],
            },
            "missing": ["operations"],
            "question": "무엇을 어떻게 수정하면 좋을지 한 줄로 알려주세요.",
        }


def _compose_edit_prompt(spec: Dict[str, Any]) -> str:
    ops = spec.get("operations") or []
    keep = spec.get("keep") or []
    lines: List[str] = [
        "Edit only the specified region if a selection mask is provided; otherwise apply globally.",
        "Do not change: " + ", ".join(keep) + ".",
    ]
    if spec.get("subject"):
        lines.append(f"Subject: {spec['subject']}.")
    if spec.get("style"):
        lines.append(f"Style: {spec['style']}.")
    if spec.get("pose"):
        lines.append(f"Pose: {spec['pose']}.")
    if spec.get("background"):
        lines.append(f"Background: {spec['background']}.")
    if spec.get("mood"):
        lines.append(f"Mood: {spec['mood']}.")
    if spec.get("colors"):
        lines.append(f"Colors: {spec['colors']}.")
    # material/texture 일치 요구를 일반화 (LLM 스펙의 힌트 필드가 없다면 colors/keep으로 커버)
    if (spec.get("colors") is None) and (spec.get("style") is None):
        lines.append("Match the character's existing material/texture for any added parts.")
    if ops:
        lines.append("Operations: " + "; ".join(ops) + ".")
    lines.append("Keep character lines, composition, and lighting consistent.")
    return "\n".join(lines)

def _get_last_image_url(session_id: str) -> Optional[str]:
    try:
        sid = int(session_id) if isinstance(session_id, str) else session_id
        msgs = get_messages_by_session(sid) or []
        for m in reversed(msgs):
            if m.get('role') == 'assistant':
                content = m.get('content','')
                if content.startswith('[image] '):
                    # format: [image] URL | {...}
                    url = content.split(' ',1)[1].split(' | ',1)[0].strip()
                    if url:
                        return url
        return None
    except Exception:
        return None

def _classify_edit_intent(user_text: str) -> bool:
    try:
        from openai import OpenAI
        from app.prompts import EDIT_INTENT_SYSTEM
        import os, json
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return False
        client = OpenAI(api_key=key)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":EDIT_INTENT_SYSTEM},{"role":"user","content": user_text or ""}],
            temperature=0,
            max_tokens=10,
            response_format={"type":"json_object"}
        )
        data = json.loads(r.choices[0].message.content)
        return bool(data.get('edit') is True)
    except Exception:
        return False


# ---- Quick intent override rules --------------------------------------------
def _wants_generate_override(text: str) -> bool:
    """사용자가 '새로/생성/만들어줘/new' 등을 명시하면 생성으로 강제 전환."""
    if not text:
        return False
    return bool(re.search(r"(새(로)?|new).*?(만들|생성)|새 이미지|새로 만들어", text))

def _build_prompt(task: GenerationTask) -> str:
    """스타일/포즈/배경/분위기를 반영한 영문 프롬프트를 구성한다."""
    obj = task.object or "subject"
    pose = task.pose or "standing"
    bg = task.bg or "plain white background"
    mood = task.mood or "cute"
    style = (task.style or "illustration").lower()

    # 공통 보강 어휘
    mood_map = {
        "cute": "cute, adorable, whimsical, soft pastel colors, warm, cozy",
        "brave": "brave, heroic",
        "calm": "calm, serene",
        "cool": "cool, stylish",
    }
    mood_desc = mood_map.get(mood, mood)

    if style in ("anime", "cartoon"):
        return (
            f"anime style illustration of a {obj}, {pose}, in {bg}, "
            f"{mood_desc}, cel-shaded, clean bold outlines, large expressive eyes, soft lighting, pastel tones, high quality"
        )
    if style in ("illustration", "illustr", "vector"):
        return (
            f"flat vector illustration of a {obj}, {pose}, in {bg}, "
            f"{mood_desc}, minimal shading, clean lines, simple shapes, vibrant colors, high quality"
        )
    if style in ("pencil", "sketch"):
        return (
            f"pencil sketch of a {obj}, {pose}, in {bg}, {mood_desc}, "
            f"graphite shading, cross-hatching, paper texture, soft strokes, high quality"
        )
    if style in ("3d", "3d render"):
        return (
            f"3D render of a {obj}, {pose}, in {bg}, {mood_desc}, "
            f"soft studio lighting, realistic materials, global illumination, high quality"
        )
    # default: photo
    return (
        f"highly detailed photorealistic photograph of a {obj}, {pose}, in {bg}, "
        f"{mood_desc}, 50mm lens, shallow depth of field, natural lighting, high quality"
    )

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
        task.style = "illustration"  # 기본 스타일(일러스트)
    
    if not task.pose:
        task.pose = "standing"  # 기본 포즈
    
    if not task.bg:
        task.bg = "plain white"  # 기본 배경
    
    if not task.mood:
        task.mood = "cute"  # 기본 분위기(귀엽고 아기자기한 톤)
    
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
    """최초 메시지로 세션 타이틀 설정 (LLM 요약 제목)"""
    try:
        if not first_user_text:
            return
        from app.prompts import TITLE_PROMPT_SYSTEM
        from openai import OpenAI
        import os
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            # 키가 없으면 첫 20자 fallback
            title = (first_user_text.strip()[:20] or "새 대화")
        else:
            client = OpenAI(api_key=openai_key)
            r = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content": TITLE_PROMPT_SYSTEM},
                    {"role":"user","content": first_user_text}
                ],
                temperature=0.3,
                max_tokens=32
            )
            title = (r.choices[0].message.content or "새 대화").strip()
        # session_id가 문자열이면 정수로 변환
        session_id_int = int(session_id) if isinstance(session_id, str) else session_id
        update_session_title(session_id_int, title[:40])
    except Exception as e:
        logger.warning(f"Failed to set session title: {e}")

async def orchestrate(message: str,
                      images: List[UploadFile],
                      mask: Optional[UploadFile],
                      selection: Optional[UploadFile] = None,
                      image_path_str: Optional[str] = None,
                      session_id: str="default",
                      user_name: str="",
                      history: Optional[List[Dict[str,str]]] = None,
                      session=None,
                      intent_override: Optional[str] = None,
                      pending_id: Optional[str] = None) -> ChatResponse:
    """메인 오케스트레이션 함수"""
    # ✅ 세션/히스토리 보장
    # 규칙: 전달된 session_id가 있고 유효하면 계속 사용, 없거나 무효하면 새로 생성
    from app.database import get_user_by_name, get_chat_sessions_by_user, create_chat_session, get_chat_session
    def _is_digit_sid(s: str) -> bool:
        try:
            int(s)
            return True
        except Exception:
            return False

    # 사용자 확보
    if user_name.strip():
        user = get_user_by_name(user_name.strip())
        if not user:
            from app.database import create_user
            user = create_user(user_name.strip())
        user_id = user['id']
    else:
        # 익명 사용자 처리
        user = get_user_by_name("anonymous")
        if not user:
            from app.database import create_user
            user = create_user("anonymous")
        user_id = user['id']

    # 세션 확보: 유효한 세션 ID가 있으면 그대로 사용, 없으면 새로 생성
    need_new_session = True
    if session_id and _is_digit_sid(session_id):
        # 숫자 세션이면 존재 여부 확인
        existing_session = get_chat_session(int(session_id))
        if existing_session:
            need_new_session = False
            logger.info(f"Continuing existing session: {session_id}")

    if need_new_session:
        title = f"{user_name}님과의 대화" if user_name.strip() else "새 대화"
        new_sess = create_chat_session(user_id, title)
        session_id = str(new_sess['id'])
        logger.info(f"Created new session: {session_id}")
    
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
    # 간단한 안전 가드(폭력/불법 행위 조장 요청 차단)
    try:
        from app.safety import detect_prohibited
        violation = detect_prohibited(message)
    except Exception:
        violation = None
    if violation:
        safe_reply = (
            "죄송해요. 해당 요청은 폭력·불법 행위를 조장/미화할 수 있어 도와드릴 수 없어요.\n"
            "대신 안전하고 긍정적인 주제의 네컷 만화 아이디어를 함께 만들어볼까요?"
        )
        _save_assistant_text(session_id, safe_reply)
        return ChatResponse(reply=safe_reply, meta={"session_id": session_id})
    _maybe_set_session_title(session_id, message)

    # 펜딩 상태 조회 (세션 객체 기준)
    pending = session.pending_task if session else None
    was_asked = session.asked_once if session else False
    
    logger.info(f"ORCHESTRATE: session={session_id}, pending={pending is not None}, was_asked={was_asked}, message={message[:50]}")

    # 업로드 파일 즉시 저장(편집 대비)
    image_path = image_path_str or (ensure_saved_file(images[0]) if images else None)
    mask_path = ensure_saved_file(mask) if mask else None
    selection_path = ensure_saved_file(selection) if selection else None

    # ── Fast-path: 파일 첨부 시 기본은 편집, 단 '새로'류 문구면 생성으로 오버라이드 ──
    _msg = (message or "").strip()
    if image_path and not _wants_generate_override(_msg):
        try:
            prompt_fast = _msg if _msg else (
                "Global cleanup only: remove minor artifacts, color balance, improve sharpness. "
                "Keep original character style, line work, composition, and lighting."
            )
            out_fast = edit_image_tool(
                image_path=image_path,
                prompt=prompt_fast,
                size="1024x1024",
                selection_path=selection_path,
            )
            if isinstance(out_fast, dict) and out_fast.get("status") == "ok" and out_fast.get("url"):
                reply_fast = "사진을 바로 편집했어요."
                _save_assistant_text(session_id, reply_fast)
                _save_assistant_image(session_id, out_fast["url"], meta={"desc": "즉시 편집 실행"})
                return ChatResponse(reply=reply_fast, url=out_fast["url"], meta={"session_id": session_id})
        except Exception as e:
            logger.warning(f"Fast-path edit failed, falling back to normal flow: {e}")

    if _wants_generate_override(_msg):
        try:
            prompt_gen = re.sub(r"(이 사진|이 이미지|사진|이미지)", "", _msg) or "cute character on white background"
            out_gen = generate_image_tool(prompt=prompt_gen, size="1024x1024")
            if isinstance(out_gen, dict) and out_gen.get("status") == "ok" and out_gen.get("url"):
                reply_gen = "요청하신 스타일로 새 이미지를 만들었어요."
                _save_assistant_text(session_id, reply_gen)
                _save_assistant_image(session_id, out_gen["url"], meta={"desc": "즉시 생성 실행"})
                return ChatResponse(reply=reply_gen, url=out_gen["url"], meta={"session_id": session_id})
        except Exception as e:
            logger.warning(f"Fast-path generate failed, falling back to normal flow: {e}")
    
    # 선택/마스크가 온 경우, 편집 펜딩 태스크를 미리 구성해 2턴 없이 바로 실행 가능하도록 준비
    if (selection_path or mask_path) and not pending:
        try:
            pending = GenerationTask(intent="edit")
            if image_path:
                pending.image_path = image_path
            if mask_path:
                pending.mask_path = mask_path
            if selection_path:
                pending.selection_path = selection_path
            # 세션에 기록하여 asked_once 처리 (추가 질문 없이 실행)
            if session:
                session.set_pending_task(pending)
                was_asked = True
        except Exception:
            pass

    # ── 이미지 + 설명 기반 사용자 편집 전용 플로우(clarify-once) ─────────────
    if (intent_override in ("edit_user_image", "edit")) and (image_path):
        # 2턴: 사용자가 추가 답을 보낸 경우
        if pending_id and session and session.pending_task:
            try:
                pend_dict = session.pending_task if isinstance(session.pending_task, dict) else {}
                base_spec = pend_dict.get("spec", {})
                merged_spec = _build_edit_spec(message)["spec"]
                # 병합: 값이 있는 항목만 덮어씀
                for k, v in (merged_spec or {}).items():
                    if v:
                        base_spec[k] = v
                final_prompt = _compose_edit_prompt(base_spec)
                out = edit_image_tool(
                    image_path=pend_dict.get("image_path") or image_path,
                    prompt=final_prompt,
                    size=pend_dict.get("size") or "1024x1024",
                    selection_path=pend_dict.get("selection_path") or selection_path,
                )
                # 펜딩 해제
                session.clear_pending_task()
                reply = "요청하신 내용을 반영해 이미지를 수정할게요."
                if isinstance(out, dict) and out.get("status") == "ok" and out.get("url"):
                    _save_assistant_text(session_id, reply)
                    _save_assistant_image(session_id, out["url"], meta={"desc": "선택 영역 편집 적용"})
                    return ChatResponse(reply=reply, url=out["url"], meta={"desc": "선택 영역 편집 적용", "session_id": session_id})
                from app.error_handler import ImageGenerationError
                raise ImageGenerationError(f"편집 실패: {out}")
            except Exception as e:
                logger.error(f"edit_user_image second turn failed: {e}")
                from app.error_handler import ImageGenerationError
                raise ImageGenerationError(str(e))

        # 1턴: Clarify-Once 필요 여부 판단
        clarify = _build_edit_spec(message)
        spec, missing, question = clarify["spec"], clarify["missing"], clarify["question"]
        if missing and session and not session.asked_once:
            pend = {
                "type": "edit",
                "image_path": image_path,
                "selection_path": selection_path,
                "spec": spec,
                "size": "1024x1024",
            }
            session.set_pending_task(pend)
            reply_q = question or "원하는 수정을 한 줄로 알려주세요."
            _save_assistant_text_dedup(session_id, reply_q)
            return ChatResponse(reply=reply_q, meta={"need_more_info": True, "session_id": session_id})
        else:
            # 충분 → 바로 편집 실행
            final_prompt = _compose_edit_prompt(spec)
            out = edit_image_tool(
                image_path=image_path,
                prompt=final_prompt,
                size="1024x1024",
                selection_path=selection_path,
            )
            reply = "설명해 주신 대로 이미지를 수정할게요."
            if isinstance(out, dict) and out.get("status") == "ok" and out.get("url"):
                _save_assistant_text(session_id, reply)
                _save_assistant_image(session_id, out["url"], meta={"desc": "선택 영역 편집 적용"})
                return ChatResponse(reply=reply, url=out["url"], meta={"desc": "선택 영역 편집 적용", "session_id": session_id})
            from app.error_handler import ImageGenerationError
            raise ImageGenerationError(f"편집 실패: {out}")

    # Core policy: Fast-path (충분 정보면 바로 실행) + Clarify 1회 (불충분시에만)
    # 선택/마스크 기반 편집은 질문 없이 바로 실행
    if pending and pending.intent == "edit" and (getattr(pending, 'selection_path', None) or getattr(pending, 'mask_path', None)):
        decision = RouterDecision(next_action="run", task=pending)
    elif not was_asked and pending is None:
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
            # 라우터가 chat으로 본 경우에도, 최근 이미지가 있고 메시지가 편집 의도면 편집으로 전환
            try:
                if _classify_edit_intent(message):
                    last_url = _get_last_image_url(session_id)
                    if last_url:
                        # 최근 이미지를 편집 대상으로 설정
                        t = GenerationTask(intent="edit", image_path=last_url)
                        decision = RouterDecision(next_action="run", task=t)
                        logger.info("ROUTER CHAT->EDIT: Recent image edit intent detected")
                    else:
                        logger.info("ROUTER CHAT: no recent image to edit")
                else:
                    logger.info("ROUTER CHAT: general conversation")
            except Exception:
                logger.info("ROUTER CHAT: fallback to general conversation")
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
                
                # 프롬프트 생성 (부족한 정보는 기본값으로) - 스타일 템플릿 반영
                pending.prompt_en = _build_prompt(pending)
                
                logger.info("SECOND TURN: 의도 유지, 기본값으로 실행")
            elif decision.next_action == "chat":
                # 의도 변경 → 대화 전환
                if session:
                    session.clear_pending_task()
                logger.info("SECOND TURN: 의도 변경, 대화 전환")
        elif pending:
            # 펜딩이 있으면 두 번째 턴부터는 라우터 재호출 없이 바로 실행(run)
            slots = _extract_slots_from_message(message)
            for key, value in slots.items():
                setattr(pending, key, value)
            if getattr(pending, 'intent', None) is None:
                pending.intent = 'generate'
            if pending.intent == 'generate':
                pending = _fill_defaults(pending, message)
                pending.prompt_en = _build_prompt(pending)
            decision = RouterDecision(next_action="run", task=pending)
            logger.info("PENDING FAST-RUN: execute without re-routing")
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
            
            # LLM 기반으로 상황 맞춤 질문 생성 (실패 시 템플릿 폴백)
            from app.prompts import ASK_CLARIFY_SYSTEM_PROMPT, render_clarify_once
            from openai import OpenAI
            import os
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
            try:
                openai_key = os.getenv("OPENAI_API_KEY")
                if not openai_key:
                    raise ValueError("OPENAI_API_KEY not found")
                client = OpenAI(api_key=openai_key)
                system_prompt = ASK_CLARIFY_SYSTEM_PROMPT + f"\n\n현재 상황: 사용자가 '{message}'라고 요청했습니다. 객체는 '{obj_kr}'이고 형용사는 '{adj}'입니다."
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"{adj} {obj_kr} 사진을 만들어주세요"}
                    ],
                    temperature=0.6,
                    max_tokens=300
                )
                clarify_question = (response.choices[0].message.content or "").strip()
                if not clarify_question:
                    raise RuntimeError("empty_clarify")
            except Exception as e:
                logger.warning(f"Clarify LLM failed, fallback to template: {e}")
                clarify_question = render_clarify_once(user_name=user_name, obj_kr=obj_kr, adj=adj)
            
            _save_assistant_text_dedup(session_id, clarify_question)
            return ChatResponse(reply=clarify_question, meta={"need_more_info": True, "session_id": session_id})
        else:
            # 이미 질문했으면 강제로 실행 (기본값으로 보정)
            if pending:
                slots = _extract_slots_from_message(message)
                for key, value in slots.items():
                    setattr(pending, key, value)
                
                # 프롬프트 생성 (기본값 보강: 귀엽고 따뜻한 분위기)
                style_str = pending.style or "illustration"
                bg_str = pending.bg or "white background"
                pose_str = pending.pose or "natural pose"
                obj_str = pending.object or "subject"
                pending.prompt_en = (
                    f"A {style_str} style {obj_str} in {bg_str}, {pose_str}, cute, warm, cozy, high quality"
                )
                
                decision = RouterDecision(next_action="run", task=pending)
                logger.info("FORCED RUN: already asked, using defaults")
            else:
                from app.prompts import get_general_chat_response
                reply = get_general_chat_response(user_name)
                _save_assistant_text(session_id, reply)
                return ChatResponse(reply=reply, meta={"session_id": session_id})

    if decision.next_action == "chat":
        # prompts.py의 프롬프트 사용
        from app.prompts import CHAT_NO_ONBOARDING_PROMPT
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
                    {"role": "system", "content": CHAT_NO_ONBOARDING_PROMPT},
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
        return ChatResponse(reply=reply, meta={"session_id": session_id})

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
        if selection_path and not getattr(task, 'selection_path', None):
            task.selection_path = selection_path

    payload = task.model_dump()
    logger.info(f"EXECUTING: {payload}")
    
    # 실행 확정 시에만 펜딩 제거
    if session:
        session.clear_pending_task()
    
    try:
        # 편집 태스크 사전 보강: 이미지/프롬프트
        if payload.get("intent") == "edit":
            # 이미지 경로 보강: 없으면 최근 이미지 사용, 그래도 없으면 질문 1회
            if not payload.get("image_path"):
                last_url = _get_last_image_url(session_id)
                if last_url:
                    payload["image_path"] = last_url
                else:
                    ask_img = "편집할 사진을 올려 주세요. 방금 만든 이미지를 쓰려면 '방금 이미지로'라고 답해도 좋아요."
                    _save_assistant_text_dedup(session_id, ask_img)
                    return ChatResponse(reply=ask_img, meta={"need_more_info": True, "session_id": session_id})

            # 프롬프트 보강: 없으면 LLM으로 스펙화 후 합성
            if not (payload.get("prompt_en") or payload.get("prompt") or payload.get("prompt_kr")):
                spec_out = _build_edit_spec(message)
                spec = spec_out.get("spec") or {}
                missing = spec_out.get("missing") or []
                if missing:
                    q = spec_out.get("question") or "원하는 수정을 한 줄로 알려주세요."
                    _save_assistant_text(session_id, q)
                    return ChatResponse(reply=q, meta={"need_more_info": True, "session_id": session_id})
                final_prompt = _compose_edit_prompt(spec)
                payload["prompt_en"] = final_prompt

        # ADK 에이전트에 JSON 태스크 전달(최우선)
        import json
        task_json = json.dumps(payload, ensure_ascii=False)
        try:
            # ADK 토글 및 타임아웃 지원
            import os
            use_adk = os.getenv("USE_ADK", "true").lower() not in ("0","false","no")
            timeout_s = float(os.getenv("ADK_TIMEOUT", "25"))
            if use_adk:
                from app.adk import adk_run
                out = adk_run(task_json, timeout=timeout_s)
            else:
                raise RuntimeError("ADK disabled by USE_ADK env")
        except Exception as adk_err:
            logger.warning(f"ADK run failed, falling back to direct tools: {adk_err}")
            # Direct tool call 폴백. 프롬프트 구성/가드.
            raw_prompt = payload.get("prompt_en") or payload.get("prompt") or payload.get("prompt_kr")
            if not raw_prompt or not str(raw_prompt).strip():
                if task.intent == "edit" and (getattr(task, 'selection_path', None) or getattr(task, 'mask_path', None)):
                    try:
                        from app.prompts import EDIT_PROMPT_SYSTEM, DEFAULT_EDIT_INSTRUCTION_KR
                        from openai import OpenAI
                        import os
                        openai_key = os.getenv("OPENAI_API_KEY")
                        if not openai_key:
                            raise ValueError("OPENAI_API_KEY not found in environment variables")
                        client = OpenAI(api_key=openai_key)
                        user_edit_text = (message or DEFAULT_EDIT_INSTRUCTION_KR)
                        r = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role":"system","content":EDIT_PROMPT_SYSTEM},{"role":"user","content": user_edit_text}],
                            temperature=0.2,max_tokens=120
                        )
                        refined = r.choices[0].message.content or "Edit only the selected area while preserving the original style."
                        raw_prompt = refined.strip()
                    except Exception:
                        raw_prompt = (message or DEFAULT_EDIT_INSTRUCTION_KR)
                else:
                    raw_prompt = _build_prompt(task)

            if payload.get("intent") == "generate":
                out = generate_image_tool(prompt=raw_prompt, size=payload.get("size", "1024x1024"))
            else:
                out = edit_image_tool(
                    image_path=payload.get("image_path"),
                    prompt=raw_prompt,
                    mask_path=payload.get("mask_path"),
                    selection_path=payload.get("selection_path"),
                    size=payload.get("size", "1024x1024")
                )

        if isinstance(out, dict) and out.get("status") == "ok" and out.get("url"):
            # prompts 기반 내레이션/요약 렌더링
            from app.prompts import render_image_result
            rendered = render_image_result(task)
            reply = rendered.get("confirm") or rendered.get("reply")
            summary = rendered.get("summary")
            desc = rendered.get("desc")

            # 온보딩 관련 추가 멘트는 더 이상 붙이지 않음

            # ✅ 결과 저장
            _save_assistant_text(session_id, reply)
            _save_assistant_image(session_id, out["url"], meta={"task": task.model_dump(), "desc": desc})

            return ChatResponse(reply=reply, url=out["url"], meta={"summary": summary, "desc": desc, "session_id": session_id})

        # 실패 처리
        detail = out if isinstance(out, str) else (out.get("detail") if isinstance(out, dict) else "unknown")
        
        from app.error_handler import ImageGenerationError
        raise ImageGenerationError(f"이미지 작업에 실패했습니다: {detail}")
        
    except Exception as e:
        logger.error(f"Execution error: {e}")
        from app.error_handler import ImageGenerationError
        raise ImageGenerationError(f"이미지 작업 중 오류가 발생했습니다: {str(e)}")

    # '다시 생성' 요청 간단 처리: 최근 태스크 기반으로 품질 강화 프롬프트 재생성
    if message.strip() in ("다시 생성", "재생성", "regenerate") and history:
        # 마지막 assistant 이미지 메타에서 task 복원 시도
        try:
            last_task = task
        except Exception:
            last_task = None
        if not last_task and pending:
            last_task = pending
        if last_task:
            # 영어 프롬프트 재작성
            try:
                from app.prompts import REGENERATE_PROMPT_SYSTEM
                from openai import OpenAI
                import os
                openai_key = os.getenv("OPENAI_API_KEY")
                if not openai_key:
                    raise ValueError("OPENAI_API_KEY not found in environment variables")
                client = OpenAI(api_key=openai_key)
                base_prompt = payload.get("prompt_en") or payload.get("prompt") or _build_prompt(last_task)
                rr = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"system","content":REGENERATE_PROMPT_SYSTEM},{"role":"user","content":base_prompt}],
                    temperature=0.4,max_tokens=120
                )
                refined_prompt = rr.choices[0].message.content.strip() or base_prompt
            except Exception:
                refined_prompt = _build_prompt(last_task)
            response = generate_image_tool(prompt=refined_prompt, size=last_task.size if getattr(last_task,'size',None) else "1024x1024")
            if isinstance(response, dict) and response.get("status") == "ok" and response.get("url"):
                from app.prompts import render_image_result
                rendered = render_image_result(last_task)
                reply = rendered.get("confirm") or "이미지를 다시 생성할게요."
                _save_assistant_text(session_id, reply)
                _save_assistant_image(session_id, response["url"], meta={"task": last_task.model_dump() if hasattr(last_task,'model_dump') else {}, "desc": rendered.get("desc")})
                return ChatResponse(reply=reply, url=response["url"], meta={"summary": rendered.get("summary"), "desc": rendered.get("desc"), "session_id": session_id})
