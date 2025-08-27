import os
import base64
import uuid
import requests
from typing import Optional, Dict, List
from fastapi import UploadFile
from PIL import Image
import numpy as np
from urllib.parse import urlparse

from openai import OpenAI, AzureOpenAI
from app.settings import settings

def _get_client():
    """OpenAI or Azure OpenAI 클라이언트 반환"""
    if settings.USE_AZURE_OPENAI:
        if not (settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_VERSION):
            raise ValueError("Azure OpenAI 설정이 부족합니다.")
        return AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        )
    key = (settings.OPENAI_API_KEY or "").strip()
    if not key or key.startswith("your-api"):
        raise ValueError("OPENAI_API_KEY가 비어있거나 placeholder입니다.")
    return OpenAI(api_key=key)

OUT_DIR = os.path.join(os.path.dirname(__file__), "static", "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

def _save_b64_png(b64: str) -> str:
    if not b64:
        raise ValueError("b64 데이터가 없습니다.")
    data = base64.b64decode(b64)
    name = f"{uuid.uuid4().hex}.png"
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as f: f.write(data)
    return f"/static/outputs/{name}"

def _save_url_png(url: str) -> str:
    if not url:
        raise ValueError("이미지 URL이 없습니다.")
    name = f"{uuid.uuid4().hex}.png"
    path = os.path.join(OUT_DIR, name)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return f"/static/outputs/{name}"

def build_alpha_mask_from_selection(selection_path: str, base_image_path: str) -> str:
    """
    selection_path: 브러시 선택 썸네일(검정/흰 배경) 파일의 URL(/static/outputs/...)
    base_image_path: 원본 이미지 URL(/static/outputs/...)
    반환: OpenAI 편집용 마스크 PNG의 URL(/static/outputs/...)
    - 마스크 규칙: '투명한(α=0) 영역'이 편집 대상. 나머지는 불투명(α=255).
    """
    if not selection_path or not base_image_path:
        raise ValueError("selection_path와 base_image_path가 필요합니다.")

    # URL → 로컬 경로 치환
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    sel_abs = selection_path.replace("/static/", static_dir + "/")
    base_abs = base_image_path.replace("/static/", static_dir + "/")

    base = Image.open(base_abs).convert("RGBA")
    sel = Image.open(sel_abs).convert("L")  # 그레이스케일
    # 크기 일치 (계단 현상 방지 위해 NEAREST)
    sel = sel.resize(base.size, resample=Image.NEAREST)

    arr = np.array(sel)

    # 배경이 밝고(흰색) 선택부가 어두운(검정) 경우가 일반적 → 임계값으로 분리
    thr = 200
    selected = arr < thr          # True = 사용자가 칠한 부분(어두움)
    alpha = np.where(selected, 0, 255).astype("uint8")  # 선택부 = 투명(0), 나머지 = 불투명(255)

    mask_rgba = Image.new("RGBA", base.size, (255, 255, 255, 255))
    mask_rgba.putalpha(Image.fromarray(alpha))

    out_name = f"mask_{uuid.uuid4().hex}.png"
    out_abs = os.path.join(OUT_DIR, out_name)
    mask_rgba.save(out_abs, "PNG")
    return f"/static/outputs/{out_name}"

def ensure_saved_file(up: Optional[UploadFile]) -> Optional[str]:
    if not up:
        return None
    name = f"{uuid.uuid4().hex}_{up.filename or 'file'}"
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as f:
        f.write(up.file.read())
    return f"/static/outputs/{name}"

def generate_image_tool(prompt: str, size: str="1024x1024"):
    # DALL·E 3 이미지 생성 (지원 크기: 1024x1024, 1024x1536, 1536x1024, 1792x1024, 1024x1792)
    if not prompt or not str(prompt).strip():
        return {"status": "error", "detail": "이미지 프롬프트가 비어 있습니다."}
    client = _get_client()
    try:
        model_name = (
            settings.AZURE_OPENAI_DEPLOYMENT_IMAGE if settings.USE_AZURE_OPENAI else "dall-e-3"
        )
        resp = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=size,
            n=1,
            response_format="b64_json",
        )
        data = resp.data[0]
        b64 = getattr(data, "b64_json", None)
        if b64:
            url = _save_b64_png(b64)
        else:
            url_field = getattr(data, "url", None)
            url = _save_url_png(url_field)
        return {"status": "ok", "url": url}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

def _resolve_abs_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    # Normalize URL -> path
    if p.startswith("http://") or p.startswith("https://"):
        try:
            path = urlparse(p).path or p
            p = path
        except Exception:
            pass
    # Map /static/... to app/static
    if p.startswith("/static/"):
        abs_path = os.path.join(static_dir, p[len("/static/"):])
    elif p.startswith("static/"):
        abs_path = os.path.join(os.path.dirname(__file__), p)
    else:
        # last resort: relative to project/app
        abs_path = os.path.join(os.path.dirname(__file__), p.lstrip("/"))
    # If still not exists, try CWD fallbacks
    if not os.path.exists(abs_path):
        alt = os.path.join(os.getcwd(), p.lstrip("/"))
        if os.path.exists(alt):
            return alt
    return abs_path

def _images_edit_rest(image_abs: str, mask_abs: Optional[str], prompt: str, size: str, model: str = "dall-e-2") -> Dict[str, str]:
    key = (settings.OPENAI_API_KEY or "").strip()
    if not key:
        return {"status":"error","detail":"OPENAI_API_KEY missing"}
    url = "https://api.openai.com/v1/images/edits"
    headers = {"Authorization": f"Bearer {key}"}
    # Ensure PNG format for both image and mask (DALL·E 2 requirement)
    def _ensure_png(abs_path: str) -> str:
        try:
            img = Image.open(abs_path)
            if getattr(img, "format", None) == "PNG":
                return abs_path
            # convert to PNG
            png_name = os.path.splitext(os.path.basename(abs_path))[0] + "_as_png.png"
            png_abs = os.path.join(OUT_DIR, png_name)
            img.convert("RGBA").save(png_abs, "PNG")
            return png_abs
        except Exception:
            # if conversion fails, still try original
            return abs_path

    image_png_abs = _ensure_png(image_abs)
    mask_png_abs = _ensure_png(mask_abs) if mask_abs else None

    files = {
        "image": (os.path.basename(image_png_abs), open(image_png_abs, "rb"), "image/png")
    }
    if mask_abs and os.path.exists(mask_abs):
        files["mask"] = (os.path.basename(mask_png_abs or mask_abs), open(mask_png_abs or mask_abs, "rb"), "image/png")
    data = {
        "model": model,
        "prompt": prompt,
        "size": size
    }
    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=90)
        j = resp.json()
        if resp.status_code >= 400:
            return {"status":"error","detail": j.get("error",{}).get("message", f"HTTP {resp.status_code}")}
        first = (j.get("data") or [{}])[0]
        b64 = first.get("b64_json")
        if b64:
            out_url = _save_b64_png(b64)
            return {"status":"ok","url": out_url}
        url_field = first.get("url")
        if url_field:
            out_url = _save_url_png(url_field)
            return {"status":"ok","url": out_url}
        return {"status":"error","detail":"No image payload in response"}
    except Exception as e:
        return {"status":"error","detail": str(e)}
    finally:
        try:
            files["image"][1].close()
        except Exception:
            pass
        if "mask" in files:
            try:
                files["mask"][1].close()
            except Exception:
                pass

def edit_image_tool(image_path: str, prompt: str, size: str="1024x1024", mask_path: Optional[str]=None, selection_path: Optional[str]=None):
    # 편집: image + (optional) mask. 무마스크도 글로벌 편집으로 DALL·E 2 REST 사용
    if not prompt or not str(prompt).strip():
        return {"status": "error", "detail": "이미지 편집 프롬프트가 비어 있습니다."}
    _ = _get_client()  # 키 검증용 (예외 발생 시 상위로 에러 전달)

    # 선택 썸네일이 있고 마스크가 없으면 생성
    if (not mask_path) and selection_path:
        try:
            mask_path = build_alpha_mask_from_selection(selection_path, image_path)
        except Exception as e:
            return {"status": "error", "detail": f"마스크 생성 실패: {str(e)}"}

    # URL → 로컬 절대경로 치환 (항상 app/static 하위)
    image_abs = _resolve_abs_path(image_path)
    mask_abs = _resolve_abs_path(mask_path)

    # 무조건 DALL·E 2 REST 편집 경로로 호출 (무마스크=글로벌 편집)
    try:
        return _images_edit_rest(image_abs, mask_abs, prompt, size, model="dall-e-2")
    except Exception as e:
        return {"status": "error", "detail": str(e)}

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