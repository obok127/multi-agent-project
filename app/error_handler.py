import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException
from openai import OpenAIError
import traceback

logger = logging.getLogger(__name__)

class ChatServiceError(Exception):
    """채팅 서비스 기본 에러"""
    def __init__(self, message: str, error_code: str = "UNKNOWN_ERROR", details: Optional[Dict] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

class OnboardingError(ChatServiceError):
    """온보딩 관련 에러"""
    pass

class ImageGenerationError(ChatServiceError):
    """이미지 생성 관련 에러"""
    pass

class RouterError(ChatServiceError):
    """라우터 관련 에러"""
    pass

def handle_exception(e: Exception, context: str = "unknown") -> Dict[str, Any]:
    """예외를 사용자 친화적 메시지로 변환"""
    
    # 로깅
    logger.error(f"Error in {context}: {str(e)}", exc_info=True)
    
    # OpenAI API 에러
    if isinstance(e, OpenAIError):
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            return {
                "reply": "죄송해요, 현재 서비스 사용량이 많아서 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
                "error_code": "QUOTA_EXCEEDED"
            }
        elif "invalid" in str(e).lower() or "model" in str(e).lower():
            return {
                "reply": "죄송해요, 이미지 생성에 문제가 발생했습니다. 다른 스타일이나 내용으로 다시 시도해주세요.",
                "error_code": "INVALID_REQUEST"
            }
        else:
            return {
                "reply": "죄송해요, AI 서비스에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
                "error_code": "OPENAI_ERROR"
            }
    
    # 커스텀 에러
    elif isinstance(e, ChatServiceError):
        return {
            "reply": e.message,
            "error_code": e.error_code,
            "details": e.details
        }
    
    # 일반적인 에러
    else:
        # 개발 환경에서는 상세 에러 정보 제공
        import os
        if os.getenv("ENVIRONMENT") == "development":
            return {
                "reply": f"개발자용 에러: {str(e)}",
                "error_code": "DEVELOPMENT_ERROR",
                "details": {"traceback": traceback.format_exc()}
            }
        else:
            # 에러 타입에 따른 구체적인 메시지
            error_type = type(e).__name__
            if "API" in error_type or "Key" in error_type:
                return {
                    "reply": "API 키 설정에 문제가 있습니다. 관리자에게 문의해주세요.",
                    "error_code": "API_KEY_ERROR"
                }
            elif "Network" in error_type or "Connection" in error_type:
                return {
                    "reply": "네트워크 연결에 문제가 있습니다. 인터넷 연결을 확인해주세요.",
                    "error_code": "NETWORK_ERROR"
                }
            else:
                return {
                    "reply": f"죄송해요, {error_type} 오류가 발생했습니다. 다시 시도해주세요.",
                    "error_code": "UNKNOWN_ERROR"
                }

def safe_execute(func, *args, **kwargs):
    """안전한 함수 실행 래퍼"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_result = handle_exception(e, f"{func.__name__}")
        raise ChatServiceError(
            message=error_result["reply"],
            error_code=error_result["error_code"],
            details=error_result.get("details")
        )
