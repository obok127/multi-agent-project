from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict

class AgentResponse(BaseModel):
    status: str = Field(..., description="ok or error")
    mode: str = Field(..., description="generate or edit")
    filename: Optional[str] = None
    url: Optional[str] = None
    detail: Optional[str] = Field(None, alias="message")  # ← 로깅 충돌 방지

# 새로운 아키텍처용 스키마 (기존과 충돌 없음)
Intent = Literal["generate", "edit", "chat"]

class RouterOut(BaseModel):
    intent: Intent
    object: Optional[str] = None
    style: Optional[str] = None
    mood: Optional[str] = None
    pose: Optional[str] = None
    bg: Optional[str] = None
    prompt_en: Optional[str] = None
    need_reference_analysis: bool = False

class OrchestratorResult(BaseModel):
    status: Literal["ok", "error"]
    mode: Intent
    url: Optional[str] = None
    filename: Optional[str] = None
    detail: Optional[str] = None  # ← 로깅 충돌 방지(message 금지)

class ChatResponse(BaseModel):
    reply: Optional[str] = None
    url: Optional[str] = None
    meta: Optional[Dict] = None

# 새로운 GenerationTask 스키마 (필수 슬롯 정의)
class GenerationTask(BaseModel):
    intent: Literal["generate", "edit"]
    object: Optional[str] = None
    style: Optional[str] = None     # "photo" | "anime" | "illustration" ...
    mood: Optional[str] = None
    pose: Optional[str] = None
    bg: Optional[str] = None
    size: str = "1024x1024"
    prompt_en: Optional[str] = None
    image_path: Optional[str] = None
    mask_path: Optional[str] = None
    selection_path: Optional[str] = None

    def is_complete(self) -> bool:
        if self.intent == "generate":
            # 스타일이 없다면 실사(photo)로 기본값 허용(패스트 패스 허용)
            return bool(self.object and (self.style or "photo"))
        if self.intent == "edit":
            return bool(self.image_path and (self.mask_path or self.prompt_en))
        return False

class RouterDecision(BaseModel):
    next_action: Literal["ask", "run", "chat"]
    clarify_question: Optional[str] = None
    task: Optional[GenerationTask] = None