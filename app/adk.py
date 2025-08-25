import os
from google.adk.agents import Agent
from app.tools import generate_image_tool, edit_image_tool

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

root_agent = Agent(
    name=ROOT_AGENT_NAME,
    model=ADK_MODEL,
    description="Orchestrator agent for image generation and editing tasks.",
    instruction=INSTRUCTION,
    tools=[generate_image_tool, edit_image_tool],
)