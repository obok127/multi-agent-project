from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import re
import logging

logger = logging.getLogger(__name__)

@dataclass
class ImageRequestInfo:
    """이미지 생성 요청 정보 - 절대 None을 반환하지 않음"""
    prompt: str                 # 생성/편집에 사용될 최종 프롬프트 (절대 None 금지)
    object: Optional[str] = None
    style: Optional[str] = None
    size: str = "1024x1024"
    needs_clarification: bool = False  # 추가 질문 필요 여부

def _guess_object(message: str, chat_history: List[Dict[str, Any]]) -> Optional[str]:
    """메시지와 히스토리에서 객체(대상) 추출"""
    # 현재 메시지에서 먼저 찾기
    animal_patterns = [
        r"(\w+)(?: 강아지| 고양이| 사진| 그림| 이미지)",
        r"(강아지|고양이|셰퍼드|푸들|골든|말티즈|시바|닥스훈트|말티즈|포메라니안)",
        r"(\w+)(?: 만들| 생성| 그려)"
    ]
    
    for pattern in animal_patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1)
    
    # 히스토리에서 찾기
    for msg in reversed(chat_history):
        content = msg.get('parts', [{}])[0].get('text', '')
        for pattern in animal_patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
    
    return None

def _guess_style(message: str, chat_history: List[Dict[str, Any]]) -> Optional[str]:
    """스타일 정보 추출"""
    # 현재 메시지에서 찾기
    if any(word in message for word in ["만화", "애니메이션", "애니", "카툰"]):
        return "만화/애니메이션"
    elif any(word in message for word in ["실사", "사진", "포토"]):
        return "실사"
    elif any(word in message for word in ["일러스트", "그림"]):
        return "일러스트"
    
    # 히스토리에서 찾기
    for msg in reversed(chat_history):
        content = msg.get('parts', [{}])[0].get('text', '')
        if any(word in content for word in ["만화", "애니메이션", "애니"]):
            return "만화/애니메이션"
        elif any(word in content for word in ["실사", "사진"]):
            return "실사"
        elif any(word in content for word in ["일러스트"]):
            return "일러스트"
    
    return None

def _guess_size(message: str, chat_history: List[Dict[str, Any]]) -> Optional[str]:
    """크기 정보 추출"""
    size_patterns = [
        r"(\d+x\d+)",
        r"(\d+)\s*[xX×]\s*(\d+)"
    ]
    
    for pattern in size_patterns:
        match = re.search(pattern, message)
        if match:
            if len(match.groups()) == 1:
                return match.group(1)
            else:
                return f"{match.group(1)}x{match.group(2)}"
    
    return None

def extract_image_request_info_from_history(message: str, chat_history: List[Dict[str, Any]]) -> ImageRequestInfo:
    """
    대화 히스토리를 고려하여 이미지 생성 요청 정보를 추출
    절대 None을 반환하지 않고 항상 ImageRequestInfo 객체를 반환
    """
    try:
        # 1) 힌트 수집 (메시지/히스토리에서 object/style/size 추출)
        obj = _guess_object(message, chat_history)
        style = _guess_style(message, chat_history)
        size = _guess_size(message, chat_history) or "1024x1024"
        
        logger.info("image.request.extracted", extra={
            "object": obj, 
            "style": style, 
            "size": size,
            "message": message[:50] + "..." if len(message) > 50 else message
        })
        
        # 2) 프롬프트 조립 (비워두지 말 것)
        if obj and style:
            # 완전한 정보가 있는 경우
            adj = _get_adjective(obj)
            prompt = f"{adj} {obj} {_get_pose()}, {style} 스타일, {_get_features()}"
            return ImageRequestInfo(
                prompt=prompt, 
                object=obj, 
                style=style, 
                size=size,
                needs_clarification=False
            )
        
        # 3) 정보가 부족하면 기본값으로라도 '항상' prompt를 만든다
        #    그리고 needs_clarification로 프론트/봇에게 추가 질문 트리거
        base_obj = obj or "강아지"  # 기본값
        base_style = style or "만화/애니메이션"  # 기본값
        adj = _get_adjective(base_obj)
        
        prompt = f"{adj} {base_obj} {_get_pose()}, {base_style} 스타일, {_get_features()}"
        
        return ImageRequestInfo(
            prompt=prompt,
            object=obj,
            style=style,
            size=size,
            needs_clarification=True
        )
        
    except Exception as e:
        logger.exception("image.request.extraction.failed", extra={"user_message": message})
        # 예외 발생 시에도 안전한 기본값 반환
        return ImageRequestInfo(
            prompt="귀여운 강아지 앉아있는 모습, 만화/애니메이션 스타일, 큰 눈, 사랑스러운 표정, 부드러운 색감, 따뜻하고 사랑스러운",
            object="강아지",
            style="만화/애니메이션",
            size="1024x1024",
            needs_clarification=True
        )

def _get_adjective(obj: str) -> str:
    """객체에 맞는 형용사 반환"""
    if any(word in obj for word in ["차", "자동차", "비행기", "건물", "풍경", "산", "바다"]):
        return "멋진"
    elif any(word in obj for word in ["꽃", "나무", "자연", "풍경"]):
        return "아름다운"
    else:
        return "귀여운"

def _get_pose() -> str:
    """기본 자세 반환"""
    return "앉아있는 모습"

def _get_features() -> str:
    """기본 특징 반환"""
    return "큰 눈, 사랑스러운 표정, 부드러운 색감, 따뜻하고 사랑스러운"
