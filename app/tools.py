import os
import base64
import uuid
import requests
from typing import Optional, Dict, List
from fastapi import UploadFile

from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

OUT_DIR = "static/outputs"
os.makedirs(OUT_DIR, exist_ok=True)

def _save_b64_png(b64: str) -> str:
    data = base64.b64decode(b64)
    name = f"{uuid.uuid4().hex}.png"
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as f: f.write(data)
    return f"/static/outputs/{name}"

def ensure_saved_file(up: Optional[UploadFile]) -> Optional[str]:
    if not up: return None
    name = f"{uuid.uuid4().hex}_{up.filename or 'file'}"
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as f:
        f.write(up.file.read())
    return f"/static/outputs/{name}"

def generate_image_tool(prompt: str, size: str="1024x1024"):
    # DALL-E 3 이미지 생성 (지원 크기: 1024x1024, 1024x1536, 1536x1024, 1792x1024, 1024x1792)
    resp = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size=size,
        n=1
    )
    b64 = resp.data[0].b64_json
    url = _save_b64_png(b64)
    return {"status":"ok","url":url}

def edit_image_tool(image_path: str, prompt: str, size: str="1024x1024", mask_path: Optional[str]=None):
    # 편집: image + mask (mask의 투명 부분만 수정)
    image_abs = image_path.replace("/static/","static/")
    mask_abs = mask_path.replace("/static/","static/") if mask_path else None
    with open(image_abs, "rb") as f: img_bytes = f.read()
    with open(mask_abs, "rb") as f: mask_bytes = f.read() if mask_abs else None

    # DALL-E 3는 편집을 지원하지 않으므로, 마스크가 있으면 DALL-E 2 사용
    model = "dall-e-2" if mask_path else "dall-e-3"
    
    resp = client.images.edits(
        model=model,
        image=img_bytes,
        mask=mask_bytes,
        prompt=prompt,
        size=size,
        n=1
    )
    b64 = resp.data[0].b64_json
    url = _save_b64_png(b64)
    return {"status":"ok","url":url}

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