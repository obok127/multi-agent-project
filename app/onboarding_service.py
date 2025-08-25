import logging
import re
from typing import Optional, Tuple
from app.session_manager import SessionContext
from app.database import add_message, get_onboarding_state, update_onboarding_state

logger = logging.getLogger(__name__)

GREETING = (
    "안녕하세요! 저는 **캐럿(Carat)**이에요. 🌟\n"
    "다양한 질문에 답변드리고, 이미지나 비디오, 오디오 콘텐츠를 만들어드리는 등 여러 가지 도움을 드릴 수 있어요.\n"
    "혹시 성함이 어떻게 되시나요? 앞으로 더 개인화된 서비스를 제공하기 위해 기억해두겠습니다! 😊"
)

SHORT_HELLO = "안녕하세요! 무엇을 도와드릴까요? 😊"

class OnboardingService:
    """온보딩 서비스 - 단일 진실 소스 (onboarding.py + onboarding_service.py 통합)"""
    
    def __init__(self):
        self.exclude_keywords = {
            "안녕", "졸려", "피곤", "대화", "생성", "편집", "사진", "이미지",
            "강아지", "고양이", "셰퍼드", "차", "풍경", "만화", "실사",
            "앉아", "서있", "지키", "공원", "거리", "밤", "하루", "오늘",
            "어떤", "무엇", "도와", "필요", "원해", "만들", "그려", "그림"
        }

    def should_show_greeting(self, session_name: str, history_len: int) -> bool:
        state = get_onboarding_state(session_name)
        return history_len == 0 and not state["greeted"]

    def extract_user_name(self, message: str) -> Optional[str]:
        if not message or len(message.strip()) < 2:
            return None
        korean_name_pattern = r'[가-힣]{2,4}'
        matches = re.findall(korean_name_pattern, message)
        for match in matches:
            if match not in self.exclude_keywords and self._is_likely_name(match, message):
                logger.info(f"Extracted name: {match} from message: {message}")
                return match
        return None

    def _is_likely_name(self, candidate: str, message: str) -> bool:
        if len(candidate) < 2 or len(candidate) > 4:
            return False
        if candidate in self.exclude_keywords:
            return False
        patterns = [
            f"저는 {candidate}", f"제 이름은 {candidate}", f"내 이름은 {candidate}",
            f"{candidate}입니다", f"{candidate}이에요", f"{candidate}예요",
            f"저는 {candidate}입니다", f"제 이름은 {candidate}입니다"
        ]
        txt = message.lower()
        if any(p in txt for p in patterns):
            return True
        if len(message.strip()) <= 4 and candidate == message.strip():
            return True
        return False

    def handle_onboarding(self, message: str, session: SessionContext, history_len: int = 0) -> Tuple[Optional[str], bool]:
        # 이미 온보딩 완료된 경우
        if session.is_onboarded:
            return None, False

        # 이름 추출 시도
        extracted_name = self.extract_user_name(message)
        if extracted_name:
            session.mark_onboarded(extracted_name)
            # DB 라치도 함께 업데이트하여 서버 리로드/재시작 후에도 온보딩이 반복되지 않도록 함
            try:
                update_onboarding_state(session.session_id, greeted=True)
            except Exception as e:
                logger.error(f"Failed to update onboarding state: {e}")
            try:
                add_message(session.session_id, "user", message)
                add_message(session.session_id, "assistant", f"안녕하세요, {extracted_name}님! 😊 만나서 반가워요!")
            except Exception as e:
                logger.error(f"Failed to save onboarding messages: {e}")
            resp = (
                f"안녕하세요, {extracted_name}님! 😊 만나서 반가워요!\n"
                "오늘 어떤 도움이 필요하신가요?\n"
                "• 궁금한 것이 있으시거나 질문이 있으시면 언제든 물어보세요\n"
                "• 이미지나 비디오, 음악을 만들고 싶으시다면 도와드릴게요\n"
                "• 번역이나 글 작성 같은 작업도 가능해요\n"
                "• 그냥 편하게 대화를 나누고 싶으시다면 그것도 좋아요!\n"
                "무엇을 도와드릴까요? ✨"
            )
            return resp, False

        # 첫 메시지에서만 인사 보내고 라치
        if self.should_show_greeting(session.session_id, history_len):
            update_onboarding_state(session.session_id, greeted=True)
            return GREETING, True

        # 짧은 인사에는 짧게
        if re.match(r"^(안녕|하이|헬로|반가워|안녕하세요)$", message.strip()):
            return SHORT_HELLO, False

        return None, False

# 전역 인스턴스
onboarding_service = OnboardingService()
