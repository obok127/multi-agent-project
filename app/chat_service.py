import os
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from google.genai import types
import google.generativeai as genai

from app.services.image_request import ImageRequestInfo, extract_image_request_info_from_history
from app.intents import detect_intent, Intent
from app.tools import generate_image_tool
from app.database import (
    get_user_by_name, create_user, update_last_visit,
    create_chat_session, get_chat_sessions_by_user, get_chat_session,
    add_message, get_messages_by_session, update_session_title,
    delete_chat_session
)
from app.prompts import CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# 대화용 Gemini 설정
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
CHAT_MODEL = genai.GenerativeModel('gemini-2.0-flash-exp')

class ChatIn(BaseModel):
    message: str
    user_name: Optional[str] = None
    session_id: Optional[int] = None

class ChatService:
    """채팅 비즈니스 로직 서비스"""
    
    @staticmethod
    async def process_message(payload: ChatIn) -> Dict[str, Any]:
        """채팅 메시지 처리"""
        message = (payload.message or "").strip()
        if not message:
            return {"error": "메시지가 비어있습니다."}

        # 이미지 경로 추출
        image_path = getattr(payload, 'image_path', None)

        # 채팅 세션 관리
        current_session_id = payload.session_id
        user_name = payload.user_name
        
        logger.info("chat.message.received", extra={
            "session_id": current_session_id,
            "user_name": user_name,
            "message_length": len(message)
        })
        
        # 새 세션이 필요한 경우 (세션 ID가 없는 경우에만)
        if not current_session_id and user_name:
            logger.info("session.checking")
            user = get_user_by_name(user_name)
            if user:
                # 기존 세션이 있는지 확인
                existing_sessions = get_chat_sessions_by_user(user['id'])
                if existing_sessions:
                    # 가장 최근 세션 사용
                    current_session_id = existing_sessions[0]['id']
                    logger.info("session.existing.used", extra={"session_id": current_session_id})
                else:
                    # 새 세션 생성
                    logger.info("session.new.creating")
                    title = await ChatService._generate_chat_title(message, user_name)
                    session = create_chat_session(user['id'], title)
                    current_session_id = session['id']
                    logger.info("session.new.created", extra={"session_id": current_session_id})
        
        # 대화 히스토리 준비
        chat_history = []
        if current_session_id:
            # 기존 메시지들 로드
            messages = get_messages_by_session(current_session_id)
            for msg in messages:
                role = "user" if msg['role'] == "user" else "model"
                chat_history.append({
                    "role": role,
                    "parts": [msg['content']]
                })
        
        try:
            # 시스템 프롬프트와 함께 대화 시작
            chat = CHAT_MODEL.start_chat(history=chat_history)
            
            # 시스템 프롬프트는 첫 메시지에만 포함하고, 이후에는 사용자 메시지만 전송
            if not chat_history:
                # 첫 메시지: 시스템 프롬프트 + 사용자 메시지
                full_message = f"{CHAT_SYSTEM_PROMPT}\n\n사용자: {message}"
            else:
                # 이후 메시지: 사용자 메시지만
                full_message = message
            
            response = chat.send_message(full_message)
            final_text = response.text
            
            # 의도 감지 (레이어드 분류기)
            intent_result = detect_intent(message, has_file=bool(image_path))
            
            logger.info("chat.intent.detected", extra={
                "intent": intent_result.label,
                "confidence": intent_result.confidence,
                "rationale": intent_result.rationale
            })
            
            # 이미지 URL 초기화
            image_url = None
            
            if intent_result.label == Intent.IMAGE_GENERATE:
                # ADK Agent를 통한 이미지 생성
                return await ChatService._handle_image_generation_with_adk(
                    message, chat_history, final_text, current_session_id, intent_result, chat
                )
            
            # 다른 의도들 처리
            elif intent_result.label == Intent.IMAGE_EDIT:
                if image_path:
                    # 이미지가 업로드된 경우 편집 처리
                    return await ChatService._handle_image_edit_with_adk(
                        message, chat_history, final_text, current_session_id, intent_result, chat, image_path
                    )
                else:
                    return {
                        "response": "편집할 이미지를 선택하고 수정할 부분을 칠해 주세요.",
                        "session_id": current_session_id,
                        "intent": intent_result.label
                    }
            elif intent_result.label == Intent.IMAGE_VARIANT:
                return await ChatService._handle_image_variant(
                    message, current_session_id, intent_result
                )
            elif intent_result.label == Intent.IMAGE_ANALYZE:
                # ADK Agent를 통한 이미지 분석
                return await ChatService._handle_image_analysis_with_adk(
                    message, chat_history, final_text, current_session_id, intent_result, chat
                )
            
            # 일반 대화 처리
            if current_session_id:
                add_message(current_session_id, "user", message)
                add_message(current_session_id, "assistant", final_text)
            
            return {
                "response": final_text,
                "session_id": current_session_id,
                "intent": intent_result.label
            }
            
        except Exception as e:
            logger.exception("chat.processing.failed", extra={
                "user_message": message,
                "error": str(e)
            })
            return {"response": f"오류가 발생했습니다: {e}"}
    
    @staticmethod
    async def _handle_image_generation(
        message: str, 
        chat_history: List[Dict[str, Any]], 
        final_text: str, 
        current_session_id: Optional[int], 
        intent_result: Any, 
        chat: Any = None
    ) -> Dict[str, Any]:
        """이미지 생성 처리 (폴백용)"""
        try:
            logger.info("image.generate.fallback.intent.detected", extra={"message": message})
            
            # 폴백: 직접 이미지 생성
            from app.tools import generate_image_tool
            image_result = generate_image_tool(prompt=message, size="1024x1024")
            image_url = image_result.get("url")
            
            if image_url:
                logger.info("image.generate.success", extra={"url": image_url})
                
                # 4) UX: 추가 정보가 필요하면 짧은 보조 멘트 제공
                completion_response = None
                if info.needs_clarification:
                    missing = []
                    if info.object is None: missing.append("대상(예: 고양이, 셰퍼드)")
                    if info.style is None: missing.append("스타일(예: 실사, 만화)")
                    if missing:
                        completion_message = (
                            "이미지가 생성되었습니다! 🎨✨\n"
                            f"더 멋진 결과를 위해 {', '.join(missing)}도 알려주실래요?"
                        )
                    else:
                        completion_message = "이미지가 생성되었습니다! 🎨✨"
                else:
                    # 완전한 정보가 있는 경우 상세 설명 요청
                    completion_message = f"""이미지가 생성되었습니다. 다음 형식으로 응답해주세요:

check
이미지 생성 완료
check
이미지 확인 완료

생성된 이미지에 대해 매우 상세하고 구체적으로 설명해주세요. 다음 요소들을 모두 포함해서 자세히 묘사해주세요:

1. 배경 (색상, 패턴, 환경)
2. 주요 객체의 전체적인 모습과 자세
3. 색상 (주요 색상, 무늬, 그라데이션 등)
4. 얼굴 표정 (눈, 코, 입, 표정)
5. 신체 부위별 특징 (귀, 꼬리, 발, 털 등)
6. 스타일적 특징 (만화/애니메이션 스타일의 특징)
7. 전체적인 느낌과 분위기

예시처럼 매우 구체적이고 상세하게 묘사해주세요:
"이 이미지는 흰색 배경에 앉아 있는 귀여운 오렌지색 고양이의 그림입니다. 고양이는 큰 검은색 눈, 분홍색 코, 작은 미소를 가지고 있습니다. 귀는 뾰족하고 안쪽은 분홍색입니다..." 같은 식으로요."""
                
                if chat:
                    completion_response = chat.send_message(completion_message)
                else:
                    # chat이 None인 경우 간단한 응답 생성
                    completion_response = type('Response', (), {'text': '이미지가 생성되었습니다! 🎨✨'})()
                
                # 메시지를 데이터베이스에 저장
                if current_session_id:
                    add_message(current_session_id, "user", message)
                    add_message(current_session_id, "assistant", final_text)
                    add_message(current_session_id, "assistant", completion_response.text)
                
                return {
                    "response": final_text,
                    "session_id": current_session_id,
                    "image_url": image_url,
                    "completion_response": completion_response.text,
                    "intent": intent_result.label
                }
            else:
                # 이미지 생성 실패
                error_response = "죄송합니다. 이미지 생성 중 오류가 발생했습니다. 다시 시도해주세요."
                if current_session_id:
                    add_message(current_session_id, "user", message)
                    add_message(current_session_id, "assistant", final_text)
                    add_message(current_session_id, "assistant", error_response)
                
                return {
                    "response": final_text,
                    "session_id": current_session_id,
                    "completion_response": error_response,
                    "intent": intent_result.label
                }
        except Exception as e:
            logger.exception("image.generate.failed", extra={
                "message": message,
                "error": str(e)
            })
            # 이미지 생성 실패 시 오류 메시지
            error_response = "죄송합니다. 이미지 생성 중 오류가 발생했습니다. 다시 시도해주세요."
            if current_session_id:
                add_message(current_session_id, "user", message)
                add_message(current_session_id, "assistant", final_text)
                add_message(current_session_id, "assistant", error_response)
            
            return {
                "response": final_text,
                "session_id": current_session_id,
                "completion_response": error_response,
                "intent": intent_result.label
            }
    
    @staticmethod
    async def _handle_image_variant(
        message: str, 
        current_session_id: Optional[int], 
        intent_result: Any
    ) -> Dict[str, Any]:
        """이미지 변형 처리"""
        try:
            image_result = generate_image_tool(prompt=message+" different variations", size="1024x1024")
            image_url = image_result.get("url")
            return {
                "response": "다른 버전으로 만들어볼게요.",
                "session_id": current_session_id,
                "image_url": image_url,
                "intent": intent_result.label
            }
        except Exception as e:
            logger.exception("image.variant.failed", extra={"user_message": message, "error": str(e)})
            return {
                "response": "죄송합니다. 이미지 변형 생성 중 오류가 발생했습니다.",
                "session_id": current_session_id,
                "intent": intent_result.label
            }
    
    @staticmethod
    async def _handle_image_generation_with_adk(
        message: str, 
        chat_history: List[Dict[str, Any]], 
        final_text: str, 
        current_session_id: Optional[int], 
        intent_result: Any, 
        chat: Any = None
    ) -> Dict[str, Any]:
        """ADK Agent를 통한 이미지 생성 처리"""
        try:
            from app.adk_agent import root_agent
            from app.routers.agent import RUNNER
            
            logger.info("adk.image.generate.start", extra={"message": message})
            
            # ADK Agent 실행 (대화 히스토리 포함)
            # 이전 대화 맥락을 ADK에 전달
            context_messages = []
            for msg in chat_history[-5:]:  # 최근 5개 메시지만 전달
                context_messages.append(f"{msg['role']}: {msg['parts'][0]}")
            
            full_context = "\n".join(context_messages) + f"\nuser: {message}"
            
            # ADK Runner 실행
            result = RUNNER.run()
            await result.events.send_message(full_context)
            
            logger.info("adk.image.generate.start", extra={"context_length": len(full_context)})
            
            # ADK 이벤트 스트림 처리
            image_url = None
            additional_data = {}
            response_text = ""
            tool_calls_processed = []
            
            async for event in result.events:
                logger.info("adk.event.received", extra={
                    "event_type": type(event).__name__,
                    "has_text": hasattr(event, 'text') and bool(event.text),
                    "has_tool_calls": hasattr(event, 'tool_calls') and bool(event.tool_calls)
                })
                
                # 텍스트 응답 처리
                if hasattr(event, 'text') and event.text:
                    response_text += event.text
                    logger.info("adk.text.received", extra={"text_length": len(event.text)})
                
                # 도구 호출 처리
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for tool_call in event.tool_calls:
                        tool_name = tool_call.get('name')
                        tool_args = tool_call.get('args', {})
                        tool_result = tool_call.get('result', {})
                        
                        logger.info("adk.tool.call", extra={
                            "tool_name": tool_name,
                            "has_args": bool(tool_args),
                            "has_result": bool(tool_result)
                        })
                        
                        # 도구별 결과 처리
                        if tool_name == 'generate_image_tool':
                            image_url = tool_result.get('url')
                            logger.info("adk.image.generated", extra={"image_url": image_url})
                        elif tool_name == 'web_search_tool':
                            additional_data['search_results'] = tool_result.get('results')
                            additional_data['search_query'] = tool_args.get('query')
                        elif tool_name == 'translate_tool':
                            additional_data['translation'] = tool_result.get('translated')
                            additional_data['original_text'] = tool_result.get('original')
                        elif tool_name == 'analyze_image_tool':
                            additional_data['image_analysis'] = tool_result.get('analysis')
                            additional_data['analysis_confidence'] = tool_result.get('confidence')
                        elif tool_name == 'create_variation_tool':
                            additional_data['variation_url'] = tool_result.get('variation_url')
                            additional_data['variation_style'] = tool_args.get('style')
                        elif tool_name == 'save_to_gallery_tool':
                            additional_data['gallery_saved'] = True
                            additional_data['gallery_title'] = tool_result.get('title')
                        
                        tool_calls_processed.append({
                            'name': tool_name,
                            'args': tool_args,
                            'result': tool_result
                        })
            
            logger.info("adk.processing.completed", extra={
                "response_length": len(response_text),
                "image_url": bool(image_url),
                "tool_calls_count": len(tool_calls_processed),
                "additional_data_keys": list(additional_data.keys())
            })
            
            # 메시지를 데이터베이스에 저장
            if current_session_id:
                add_message(current_session_id, "user", message)
                add_message(current_session_id, "assistant", final_text)
                if hasattr(result, 'text') and result.text:
                    add_message(current_session_id, "assistant", result.text)
            
            return {
                "response": final_text,
                "session_id": current_session_id,
                "image_url": image_url,
                "completion_response": response_text,
                "intent": intent_result.label,
                "additional_data": additional_data
            }
            
        except Exception as e:
            logger.exception("adk.image.generate.failed", extra={
                "user_message": message,
                "error": str(e)
            })
            # ADK 실패 시 폴백으로 직접 생성
            return await ChatService._handle_image_generation(
                message, chat_history, final_text, current_session_id, intent_result, chat
            )

    @staticmethod
    async def _handle_image_analysis_with_adk(
        message: str, 
        chat_history: List[Dict[str, Any]], 
        final_text: str, 
        current_session_id: Optional[int], 
        intent_result: Any, 
        chat: Any = None
    ) -> Dict[str, Any]:
        """ADK Agent를 통한 이미지 분석 처리"""
        try:
            from app.adk_agent import root_agent
            from app.routers.agent import RUNNER
            
            logger.info("adk.image.analysis.start", extra={"message": message})
            
            # ADK Agent 실행 (대화 히스토리 포함)
            context_messages = []
            for msg in chat_history[-5:]:  # 최근 5개 메시지만 전달
                context_messages.append(f"{msg['role']}: {msg['parts'][0]}")
            
            full_context = "\n".join(context_messages) + f"\nuser: {message}"
            
            # ADK Runner 실행
            result = RUNNER.run()
            await result.events.send_message(full_context)
            
            logger.info("adk.image.analysis.start", extra={"context_length": len(full_context)})
            
            # ADK 이벤트 스트림 처리
            analysis_result = None
            translation_result = None
            additional_data = {}
            response_text = ""
            tool_calls_processed = []
            
            async for event in result.events:
                logger.info("adk.analysis.event.received", extra={
                    "event_type": type(event).__name__,
                    "has_text": hasattr(event, 'text') and bool(event.text),
                    "has_tool_calls": hasattr(event, 'tool_calls') and bool(event.tool_calls)
                })
                
                # 텍스트 응답 처리
                if hasattr(event, 'text') and event.text:
                    response_text += event.text
                    logger.info("adk.analysis.text.received", extra={"text_length": len(event.text)})
                
                # 도구 호출 처리
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for tool_call in event.tool_calls:
                        tool_name = tool_call.get('name')
                        tool_args = tool_call.get('args', {})
                        tool_result = tool_call.get('result', {})
                        
                        logger.info("adk.analysis.tool.call", extra={
                            "tool_name": tool_name,
                            "has_args": bool(tool_args),
                            "has_result": bool(tool_result)
                        })
                        
                        # 도구별 결과 처리
                        if tool_name == 'analyze_image_tool':
                            analysis_result = tool_result.get('analysis')
                            additional_data['image_analysis'] = analysis_result
                            additional_data['analysis_confidence'] = tool_result.get('confidence')
                            logger.info("adk.image.analyzed", extra={"analysis_length": len(analysis_result) if analysis_result else 0})
                        elif tool_name == 'translate_tool':
                            translation_result = tool_result.get('translated')
                            additional_data['translation'] = translation_result
                            additional_data['original_text'] = tool_result.get('original')
                            logger.info("adk.translation.completed", extra={"translation_length": len(translation_result) if translation_result else 0})
                        
                        tool_calls_processed.append({
                            'name': tool_name,
                            'args': tool_args,
                            'result': tool_result
                        })
            
            logger.info("adk.analysis.completed", extra={
                "response_length": len(response_text),
                "analysis_result": bool(analysis_result),
                "translation_result": bool(translation_result),
                "tool_calls_count": len(tool_calls_processed)
            })
            
            # 메시지를 데이터베이스에 저장
            if current_session_id:
                add_message(current_session_id, "user", message)
                add_message(current_session_id, "assistant", final_text)
                if hasattr(result, 'text') and result.text:
                    add_message(current_session_id, "assistant", result.text)
            
            return {
                "response": final_text,
                "session_id": current_session_id,
                "completion_response": result.text if hasattr(result, 'text') else None,
                "intent": intent_result.label,
                "additional_data": additional_data
            }
            
        except Exception as e:
            logger.exception("adk.image.analysis.failed", extra={
                "user_message": message,
                "error": str(e)
            })
            return {
                "response": "이미지 분석 중 오류가 발생했습니다.",
                "session_id": current_session_id,
                "intent": intent_result.label
            }

    @staticmethod
    async def _handle_image_edit_with_adk(
        message: str, 
        chat_history: List[Dict[str, Any]], 
        final_text: str, 
        current_session_id: Optional[int], 
        intent_result: Any, 
        chat: Any = None,
        image_path: str = None
    ) -> Dict[str, Any]:
        """ADK Agent를 통한 이미지 편집 처리"""
        try:
            from app.adk_agent import root_agent
            from app.routers.agent import RUNNER
            
            logger.info("adk.image.edit.start", extra={"message": message, "image_path": image_path})
            
            # ADK Agent 실행 (대화 히스토리 포함)
            context_messages = []
            for msg in chat_history[-5:]:  # 최근 5개 메시지만 전달
                context_messages.append(f"{msg['role']}: {msg['parts'][0]}")
            
            full_context = "\n".join(context_messages) + f"\nuser: {message}\nimage_path: {image_path}"
            
            # ADK Runner 실행
            result = RUNNER.run()
            await result.events.send_message(full_context)
            
            logger.info("adk.image.edit.start", extra={"context_length": len(full_context)})
            
            # ADK 이벤트 스트림 처리
            edited_image_url = None
            additional_data = {}
            response_text = ""
            tool_calls_processed = []
            
            async for event in result.events:
                logger.info("adk.edit.event.received", extra={
                    "event_type": type(event).__name__,
                    "has_text": hasattr(event, 'text') and bool(event.text),
                    "has_tool_calls": hasattr(event, 'tool_calls') and bool(event.tool_calls)
                })
                
                # 텍스트 응답 처리
                if hasattr(event, 'text') and event.text:
                    response_text += event.text
                    logger.info("adk.edit.text.received", extra={"text_length": len(event.text)})
                
                # 도구 호출 처리
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for tool_call in event.tool_calls:
                        tool_name = tool_call.get('name')
                        tool_args = tool_call.get('args', {})
                        tool_result = tool_call.get('result', {})
                        
                        logger.info("adk.edit.tool.call", extra={
                            "tool_name": tool_name,
                            "has_args": bool(tool_args),
                            "has_result": bool(tool_result)
                        })
                        
                        # 도구별 결과 처리
                        if tool_name == 'edit_image_tool':
                            edited_image_url = tool_result.get('url')
                            logger.info("adk.image.edited", extra={"edited_image_url": edited_image_url})
                        
                        tool_calls_processed.append({
                            'name': tool_name,
                            'args': tool_args,
                            'result': tool_result
                        })
            
            logger.info("adk.edit.completed", extra={
                "response_length": len(response_text),
                "edited_image_url": bool(edited_image_url),
                "tool_calls_count": len(tool_calls_processed)
            })
            
            # 메시지를 데이터베이스에 저장
            if current_session_id:
                add_message(current_session_id, "user", message)
                add_message(current_session_id, "assistant", final_text)
                if response_text:
                    add_message(current_session_id, "assistant", response_text)
            
            return {
                "response": final_text,
                "session_id": current_session_id,
                "image_url": edited_image_url,
                "completion_response": response_text,
                "intent": intent_result.label,
                "additional_data": additional_data
            }
            
        except Exception as e:
            logger.exception("adk.image.edit.failed", extra={
                "user_message": message,
                "error": str(e)
            })
            return {
                "response": "이미지 편집 중 오류가 발생했습니다.",
                "session_id": current_session_id,
                "intent": intent_result.label
            }

    @staticmethod
    async def _generate_chat_title(message: str, user_name: str) -> str:
        """LLM을 사용하여 채팅 세션 제목을 생성"""
        try:
            # 간단한 제목 생성 로직
            if "이미지" in message or "사진" in message or "그림" in message:
                return f"{user_name}님의 이미지 생성 요청"
            elif "요약" in message or "정리" in message:
                return f"{user_name}님의 요약 요청"
            elif "번역" in message:
                return f"{user_name}님의 번역 요청"
            else:
                return f"{user_name}님과의 대화"
        except Exception as e:
            logger.exception("title.generation.failed", extra={"user_message": message, "user_name": user_name})
            return f"{user_name}님과의 대화"
