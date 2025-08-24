import os
import base64
import uuid
import requests
from typing import Optional, Dict, List
from openai import OpenAI

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _save_base64_png(b64: str) -> dict:
    image_bytes = base64.b64decode(b64)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    rel_url = f"/static/outputs/{filename}"
    return {"filename": filename, "url": rel_url, "abs_path": filepath}

def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=key)

def generate_image_tool(prompt: str, size: str = "1024x1024") -> Dict[str, str]:
    import logging
    logger = logging.getLogger(__name__)
    
    client = _client()
    logger.info("OpenAI API 호출 시작", extra={"prompt_length": len(prompt), "size": size})
    
    try:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            n=1,
        )
        logger.info("OpenAI API 응답 받음", extra={"response_type": type(resp).__name__})
        
        b64 = resp.data[0].b64_json
        if not b64:
            logger.error("b64_json이 None입니다", extra={"resp_data_length": len(resp.data) if resp.data else 0})
            raise RuntimeError("OpenAI API에서 이미지 데이터를 받지 못했습니다")
        
        logger.info("이미지 데이터 추출 성공", extra={"b64_length": len(b64)})
        saved = _save_base64_png(b64)
        return {"status": "ok", "mode": "generate", "filename": saved["filename"], "url": saved["url"]}
    except Exception as e:
        logger.exception("OpenAI API 호출 실패", extra={"error_type": type(e).__name__, "error_msg": str(e)})
        raise

def edit_image_tool(image_path: str, prompt: str, size: str = "1024x1024", mask_path: Optional[str] = None) -> Dict[str, str]:
    client = _client()
    with open(image_path, "rb") as img_f:
        if mask_path:
            with open(mask_path, "rb") as mask_f:
                resp = client.images.edits(
                    model="dall-e-3",
                    image=img_f,
                    mask=mask_f,
                    prompt=prompt,
                    size=size,
                    n=1,
                )
        else:
            resp = client.images.edits(
                model="dall-e-3",
                image=img_f,
                prompt=prompt,
                size=size,
                n=1,
            )
    b64 = resp.data[0].b64_json
    saved = _save_base64_png(b64)
    return {"status": "ok", "mode": "edit", "filename": saved["filename"], "url": saved["url"]}

# ADK Agent를 위한 추가 도구들
def web_search_tool(query: str) -> Dict[str, str]:
    """웹 검색 도구 - 최신 정보 제공"""
    try:
        # 실제 구현에서는 검색 API 사용
        return {
            "status": "ok",
            "query": query,
            "results": f"'{query}'에 대한 최신 정보를 검색했습니다.",
            "sources": ["검색 결과 1", "검색 결과 2"]
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def translate_tool(text: str, target_language: str = "en") -> Dict[str, str]:
    """번역 도구"""
    try:
        # 실제 구현에서는 번역 API 사용
        translations = {
            "en": "Hello, how are you?",
            "ja": "こんにちは、お元気ですか？",
            "zh": "你好，你好吗？"
        }
        return {
            "status": "ok",
            "original": text,
            "translated": translations.get(target_language, text),
            "target_language": target_language
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def analyze_image_tool(image_url: str) -> Dict[str, str]:
    """이미지 분석 도구"""
    try:
        # 실제 구현에서는 이미지 분석 API 사용
        return {
            "status": "ok",
            "image_url": image_url,
            "analysis": "이미지에 고양이가 앉아있는 모습이 보입니다. 오렌지색 털을 가진 귀여운 고양이입니다.",
            "confidence": 0.95
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def create_variation_tool(image_url: str, style: str = "similar") -> Dict[str, str]:
    """이미지 변형 생성 도구"""
    try:
        # 실제 구현에서는 이미지 변형 API 사용
        return {
            "status": "ok",
            "original_url": image_url,
            "variation_url": image_url.replace(".png", "_variation.png"),
            "style": style
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def save_to_gallery_tool(image_url: str, title: str, description: str) -> Dict[str, str]:
    """갤러리에 이미지 저장 도구"""
    try:
        # 실제 구현에서는 데이터베이스 저장
        return {
            "status": "ok",
            "image_url": image_url,
            "title": title,
            "description": description,
            "saved_at": "2024-01-01T00:00:00Z"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}