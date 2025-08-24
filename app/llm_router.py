# app/llm_router.py
import os, json
from typing import List, Dict, Optional
from app.schemas import RouterDecision, GenerationTask

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

SYSTEM = """You are a STRICT intent router for an image assistant.
You read chat history and the latest user message.

Your job:
1) If the user wants to CREATE or EDIT an image/video/audio:
   - If key slots are insufficient (style or pose or background missing), reply with a SINGLE, short Korean question to clarify (no extra prose).
     Return JSON: {"next_action":"ask","clarify_question":"..."}
   - Else, produce a compact JSON task to execute deterministically (no prose).
     Return JSON: {
        "next_action":"run",
        "task":{
           "intent":"generate|edit",
           "object":"dog|cat|German shepherd|...",
           "style":"photo|anime|illustration|3d|...",
           "mood":"brave|cute|...?",
           "pose":"standing guard|sitting|...",
           "bg":"park|night street|...",
           "size":"1024x1024|1024x1536|1536x1024",
           "prompt_en":"(English prompt, compact and specific)",
           "image_path":"... (for edit only, else null)",
           "mask_path":"... (optional)"
        }
     }
2) If it's just small talk or unrelated to creation/edit, return:
   {"next_action":"chat"}

Rules:
- Use Korean for clarify_question.
- NEVER include any text outside of JSON. Output valid JSON only.
- Prefer concise values. Set a reasonable default size (1024x1024) when missing.
- If intent is EDIT, require image_path or mention it in the clarify question.
- Consider the dialog context (history) when inferring object/style/pose/bg.
- IMPORTANT: If PENDING_TASK_JSON exists, use it as context and combine with the user's latest response to fill missing slots.
- If the user is responding to a previous question about style/pose/background, extract the information from their response and create a complete task.
- If the user changes their mind and wants to do something else (not image generation), detect this and return "chat".
"""

def normalize_style(s: str) -> str:
    """Normalize style to prevent repeated questions"""
    if not s:
        return "photo"
    
    s = s.lower().replace(" ", "").replace("//","/").replace("\\","/")
    
    if "anime" in s or "cartoon" in s:
        return "anime"
    if "illustr" in s:
        return "illustration"
    if "photo" in s or "realistic" in s:
        return "photo"
    if "3d" in s:
        return "3d"
    
    return "photo"

def _render_history(history: List[Dict[str,str]], last_user: str, pending: Optional[GenerationTask]) -> str:
    lines = []
    for h in history[-8:]:
        role = h.get("role","user").upper()
        txt = (h.get("content","") or "").replace("\n"," ")
        if txt: 
            lines.append(f"{role}: {txt}")
    lines.append(f"USER: {last_user.replace('\n',' ')}")
    
    if pending:
        # 펜딩 상태가 있으면 명확히 표시
        pending_json = pending.model_dump_json()
        lines.append(f"PENDING_TASK_JSON: {pending_json}")
        lines.append("NOTE: User is responding to a previous question. Extract style/pose/background from their response and combine with pending task.")
    
    return "\n".join(lines)

def _openai_json_only(payload: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)
    
    # Standard OpenAI chat completions API
    r = client.chat.completions.create(
        model=os.getenv("ROUTER_MODEL","gpt-4o-mini"),
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":payload}],
        temperature=0.2,
        max_tokens=300,
        response_format={"type":"json_object"}
    )
    return r.choices[0].message.content

def _gemini_json_only(payload: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel(os.getenv("ROUTER_MODEL","gemini-2.0-flash-8b"))
    resp = model.generate_content(
        f"{SYSTEM}\n\n=== DIALOG ===\n{payload}\n\nReturn JSON only.",
        generation_config={"temperature":0.2,"max_output_tokens":400}
    )
    return resp.text or "{}"

def route_with_llm(history, last_user, pending) -> RouterDecision:
    payload = _render_history(history, last_user, pending)
    raw = None
    
    try:
        if OPENAI_KEY:
            raw = _openai_json_only(payload)
        elif GEMINI_KEY:
            raw = _gemini_json_only(payload)
        else:
            # API 키가 없으면 기본 질문
            if pending:
                return RouterDecision(next_action="run", task=pending)  # 펜딩이 있으면 실행
            return RouterDecision(next_action="ask", clarify_question="원하시는 스타일/포즈/배경을 알려주세요. (예: 만화, 앉아있는, 공원)")
        
        data = json.loads(raw)
    except Exception as e:
        # JSON 파싱 실패 시 기본 처리
        if pending:
            return RouterDecision(next_action="run", task=pending)  # 펜딩이 있으면 실행
        return RouterDecision(next_action="ask", clarify_question="원하시는 스타일/포즈/배경을 알려주세요. (예: 실사/만화, 앉아있는, 공원)")

    na = data.get("next_action")
    
    if na == "run" and data.get("task"):
        t = GenerationTask(**data["task"])
        if not t.size: 
            t.size = "1024x1024"
        
        # 스타일 정규화
        if t.style:
            t.style = normalize_style(t.style)
        
        return RouterDecision(next_action="run", task=t)
    
    if na == "ask" and data.get("clarify_question"):
        return RouterDecision(next_action="ask", clarify_question=data["clarify_question"])
    
    return RouterDecision(next_action="chat")
