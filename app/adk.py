import os
from typing import Any, Dict

# Ensure 'app' package is importable even if executed in non-package context
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

ADK_AVAILABLE = True
try:
    from google.adk.agents import Agent  # type: ignore
except Exception:
    ADK_AVAILABLE = False
    Agent = object  # placeholder

from app.tools import generate_image_tool, edit_image_tool
from app.settings import settings
try:
    from openai import OpenAI  # type: ignore
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False
from app.prompts import CHAT_NO_ONBOARDING_PROMPT, TITLE_PROMPT_SYSTEM

ROOT_AGENT_NAME = "mini_carrot_orchestrator"
ADK_MODEL = os.getenv("ADK_MODEL", "gemini-2.0-flash-8b")

INSTRUCTION = """
You receive a single JSON task:
{
  "intent": "generate|edit",
  "object": "...",
  "style": "photo|anime|illustration",
  "prompt_en": "...",
  "image_path": "...?",
  "mask_path": "...?",
  "selection_path": "...?",
  "size": "512x512|1024x1024"
}

Rules:
- If intent == "generate": call generate_image_tool(prompt=prompt_en, size=size).
- If intent == "edit": call edit_image_tool(image_path=image_path, prompt=prompt_en, mask_path=mask_path, selection_path=selection_path, size=size).
- ALWAYS return compact JSON ONLY: {"status":"ok","url":"..."} or {"status":"error","detail":"..."}.
- Do not explain. No prose. No extra fields.
"""

root_agent = None
if ADK_AVAILABLE:
    try:
        root_agent = Agent(
            name=ROOT_AGENT_NAME,
            model=ADK_MODEL,
            description="Orchestrator agent for image generation and editing tasks.",
            instruction=INSTRUCTION,
            tools=[generate_image_tool, edit_image_tool],
        )
    except Exception:
        root_agent = None


def adk_run(task_json: str, timeout: float = 25.0) -> Dict[str, Any]:
    """Run task via ADK if possible; otherwise gracefully fallback.

    Returns a dict like {"status":"ok","url":"..."} or {"status":"error","detail":"..."}
    """
    try:
        # Try ADK only if available and initialized
        if ADK_AVAILABLE and root_agent is not None:
            # Try common method names to execute the agent
            if hasattr(root_agent, "invoke"):
                res = root_agent.invoke(task_json, timeout=timeout)
            elif hasattr(root_agent, "run"):
                res = root_agent.run(task_json, timeout=timeout)
            elif hasattr(root_agent, "execute"):
                res = root_agent.execute(task_json, timeout=timeout)
            else:
                raise AttributeError("root_agent has no supported execute method")

            # Normalize response to dict
            if isinstance(res, dict):
                return res
            text = getattr(res, "text", None) or (res if isinstance(res, str) else str(res))
            import json
            return json.loads(text)
    except Exception as e:
        # Fallback: parse the JSON task and dispatch to local tools
        try:
            import json
            payload = json.loads(task_json)
            intent = (payload or {}).get("intent")
            if intent == "generate":
                return generate_image_tool(
                    prompt=payload.get("prompt_en") or payload.get("prompt") or "",
                    size=payload.get("size", "1024x1024"),
                )
            if intent == "edit":
                return edit_image_tool(
                    image_path=payload.get("image_path"),
                    prompt=payload.get("prompt_en") or payload.get("prompt") or "",
                    mask_path=payload.get("mask_path"),
                    selection_path=payload.get("selection_path"),
                    size=payload.get("size", "1024x1024"),
                )
            return {"status": "error", "detail": f"Unsupported intent: {intent}"}
        except Exception as ee:
            return {"status": "error", "detail": f"ADK+fallback failed: {str(e) or repr(e)} / {str(ee) or repr(ee)}"}