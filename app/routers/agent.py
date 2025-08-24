from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import logging

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from app.adk_agent import root_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ADK 러너 (키는 .env에서 로드됨) - /api/agent 전용
APP_NAME = "mini_carrot_app"
SESSION_SERVICE = InMemorySessionService()
RUNNER = Runner(agent=root_agent, app_name=APP_NAME, session_service=SESSION_SERVICE)

@router.post("/")
async def agent_endpoint(
    prompt: str = Form(...),
    image: Optional[UploadFile] = File(None),
    mask: Optional[UploadFile] = File(None),
    size: str = Form("1024x1024")
):
    """ADK 에이전트를 통한 이미지 생성/편집 엔드포인트"""
    try:
        logger.info("agent.request.received", extra={
            "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt,
            "has_image": image is not None,
            "has_mask": mask is not None,
            "size": size
        })
        
        # ADK 에이전트 실행
        result = RUNNER.run()
        await result.events.send_message(prompt)
        
        # 결과 처리
        response_text = ""
        image_url = None
        
        async for event in result.events:
            if hasattr(event, 'text') and event.text:
                response_text += event.text
            elif hasattr(event, 'tool_calls') and event.tool_calls:
                for tool_call in event.tool_calls:
                    if tool_call.name == "generate_image_tool":
                        # 이미지 생성 툴 호출 결과 처리
                        image_url = tool_call.result.get("url") if tool_call.result else None
        
        return JSONResponse({
            "response": response_text,
            "image_url": image_url
        })
        
    except Exception as e:
        logger.exception("agent.request.failed", extra={
            "prompt": prompt,
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"에이전트 처리 실패: {str(e)}")
