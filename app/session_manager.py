import logging
from typing import Dict, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from app.database import get_messages_by_session, get_onboarding_state

logger = logging.getLogger(__name__)

@dataclass
class SessionContext:
    """세션 컨텍스트 - 단일 진실 소스"""
    session_id: str
    user_name: Optional[str] = None
    is_onboarded: bool = False
    asked_once: bool = False
    pending_task: Optional[Dict] = None
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()
    
    def mark_onboarded(self, user_name: str):
        """온보딩 완료 표시"""
        self.user_name = user_name
        self.is_onboarded = True
        self.updated_at = datetime.utcnow()
        logger.info(f"Session {self.session_id} onboarded for user {user_name}")
    
    def set_pending_task(self, task: Dict):
        """펜딩 태스크 설정"""
        self.pending_task = task
        self.asked_once = True
        self.updated_at = datetime.utcnow()
        logger.info(f"Session {self.session_id} pending task set: {task}")
    
    def clear_pending_task(self):
        """펜딩 태스크 제거"""
        self.pending_task = None
        self.updated_at = datetime.utcnow()
        logger.info(f"Session {self.session_id} pending task cleared")
    
    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return asdict(self)

class SessionManager:
    """세션 관리자 - 단일 진실 소스"""
    
    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}
    
    def get_session(self, session_id: str) -> SessionContext:
        """세션 가져오기 (없으면 생성)"""
        if session_id not in self._sessions:
            # DB 라치 반영하여 초기화
            try:
                state = get_onboarding_state(session_id)
                ctx = SessionContext(
                    session_id=session_id,
                    user_name=state.get("user_name") if isinstance(state, dict) else None,
                    is_onboarded=bool(state.get("greeted")) if isinstance(state, dict) else False,
                    asked_once=bool(state.get("asked_once")) if isinstance(state, dict) else False,
                )
            except Exception:
                ctx = SessionContext(session_id=session_id)
            self._sessions[session_id] = ctx
            logger.info(f"New session created: {session_id}")
        return self._sessions[session_id]
    
    def update_session(self, session_id: str, **kwargs):
        """세션 업데이트"""
        session = self.get_session(session_id)
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)
        session.updated_at = datetime.utcnow()
        logger.info(f"Session {session_id} updated: {kwargs}")
    
    def get_history(self, session_id: str) -> list:
        """세션 히스토리 가져오기"""
        try:
            return get_messages_by_session(session_id) or []
        except Exception as e:
            logger.error(f"Failed to get history for session {session_id}: {e}")
            return []

# 전역 인스턴스
session_manager = SessionManager()
