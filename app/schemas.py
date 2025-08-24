from pydantic import BaseModel, Field
from typing import Optional

class AgentResponse(BaseModel):
    status: str = Field(..., description="ok or error")
    mode: str = Field(..., description="generate or edit")
    filename: Optional[str] = None
    url: Optional[str] = None
    message: Optional[str] = None