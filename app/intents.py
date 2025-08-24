from dataclasses import dataclass
from enum import StrEnum
import re
import os
from openai import OpenAI

class Intent(StrEnum):
    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT     = "image.edit"       # 마스크/부분수정/색변경/배경제거
    IMAGE_VARIANT  = "image.variation"  # 같은 이미지 다른 버전
    IMAGE_ANALYZE  = "image.analyze"    # 이미지 분석/설명
    CHITCHAT       = "chitchat"
    HELP           = "help"
    OTHER          = "other"

@dataclass
class IntentResult:
    label: Intent
    confidence: float
    rationale: str | None = None

# 자주 쓰는 동사/명사 패턴 (띄어쓰기/어미 변화·오타 일부 허용)
RX_SPACE = r"(?:\s|·|/|,|:|~|-|—|_|\.|!|\?)"
RX_WORDSEP = r"(?:\s|,|\.|!|\?|/|~|:|;|·|—|-|_|\\)+"
RX_NEG = r"(?:말고|빼고|하지\s*말고|원치\s*않|no\s*image|text\s*only)"

GEN_NOUN_KO = r"(?:이미지|사진|그림|일러스트|썸네일|로고|배경|캐릭터|포스터|스티커|짤|ai\s*그림)"
GEN_VERB_KO = r"(?:만들(?:어|어\s*줘|어\s*라)?|생성|그려(?:줘|봐|라)?|제작|렌더|뽑아)"
OBJ_HEAD_KO = r"(?:고양이|강아지|사람|인물|풍경|차|건물|아이돌|로봇|강|바다|산|도시|음식|케이크|캐릭터|셰퍼드)"

EDIT_KO = r"(?:편집|수정|바꿔|변경|합성|지워|제거|교체|색(?:상)?\s*바꿔|배경\s*제거|마스크|영역|부분)"
VAR_KO  = r"(?:다른\s*버전|버전\s*더|변형|variation|variants?)"
ANALYZE_KO = r"(?:분석|설명|뭐야|무엇|어떤|보여|알려|해석|번역)"

GEN_EN = r"(?:image|photo|picture|art|illustration|logo|sticker|thumbnail|background)"
GENV_EN = r"(?:create|make|generate|draw|render|produce)"
EDIT_EN = r"(?:edit|inpaint|erase|remove\s+background|replace|recolor|mask)"
VAR_EN  = r"(?:variation|variant|more\s+versions?)"
ANALYZE_EN = r"(?:analyze|describe|what|explain|translate|interpret)"

# 생성: 명사↔동사 순서 모두 허용, 최대 16자(한/영 혼용) 이내 근접
GEN_RULE = re.compile(
    rf"(?:({GEN_NOUN_KO}|{GEN_EN}).{{0,16}}({GEN_VERB_KO}|{GENV_EN})|"
    rf"({OBJ_HEAD_KO}).{{0,12}}({GEN_NOUN_KO}|{GEN_EN}).{{0,12}}({GEN_VERB_KO}|{GENV_EN}))",
    re.IGNORECASE
)

# 편집/부분수정
EDIT_RULE = re.compile(rf"({EDIT_KO}|{EDIT_EN})", re.IGNORECASE)

# 변형
VAR_RULE  = re.compile(rf"({VAR_KO}|{VAR_EN})", re.IGNORECASE)

# 분석
ANALYZE_RULE = re.compile(rf"({ANALYZE_KO}|{ANALYZE_EN})", re.IGNORECASE)

# 부정("이미지 말고…", "텍스트로만")
NEG_RULE  = re.compile(rf"{RX_NEG}", re.IGNORECASE)

# 코드/태그/업로드오류 등 '이미지'가 들어가도 생성 의도가 아닌 케이스 억제
NO_INTENT_RULE = re.compile(
    r"(?:img\s*tag|<img|이미지\s*태그|이미지\s*경로|업로드가\s*안|에러|오류|깨짐|안\s*보임|broken\s*image|alt\s*text)",
    re.IGNORECASE
)

def rule_based_intent(text: str, has_file: bool = False) -> IntentResult:
    t = text.strip()

    # 부정 먼저
    if NEG_RULE.search(t):
        return IntentResult(Intent.CHITCHAT, 0.6, "negated")

    # 업로드/태그/지원 이슈는 help로
    if NO_INTENT_RULE.search(t):
        return IntentResult(Intent.HELP, 0.75, "support context")

    # 파일이 같이 오면 편집 의도 가중
    if has_file and EDIT_RULE.search(t):
        return IntentResult(Intent.IMAGE_EDIT, 0.9, "file+edit keywords")

    # 단어만으로도 편집
    if EDIT_RULE.search(t):
        return IntentResult(Intent.IMAGE_EDIT, 0.8, "edit keywords")

    # 변형
    if VAR_RULE.search(t):
        return IntentResult(Intent.IMAGE_VARIANT, 0.7, "variant keywords")

    # 분석
    if ANALYZE_RULE.search(t):
        return IntentResult(Intent.IMAGE_ANALYZE, 0.8, "analyze keywords")

    # 생성
    if GEN_RULE.search(t):
        return IntentResult(Intent.IMAGE_GENERATE, 0.75, "gen near-match")

    # 객체+사진 (동사 없지만 흔한 요청)
    if re.search(rf"({OBJ_HEAD_KO}).{{0,8}}(사진|이미지)|({GEN_EN}).*",
                 t, re.IGNORECASE):
        return IntentResult(Intent.IMAGE_GENERATE, 0.6, "object+photo")

    return IntentResult(Intent.OTHER, 0.2, "no signal")

# 2차: 소형 LLM 폴백(희귀 케이스만)
ALLOW_LLM = True
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

LLM_SYS = """You are a router. Classify the user's intent.
Return compact JSON: {"label": "...", "confidence": 0.0-1.0}.
Allowed labels: image.generate, image.edit, image.variation, chitchat, help, other.
If the user negates image generation (e.g., '말고'), do NOT return image.*.
"""

def llm_fallback(text: str) -> IntentResult:
    msg = [
        {"role": "system", "content": LLM_SYS},
        {"role": "user", "content": text}
    ]
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",  # 또는 gemini-lite 등 빠른 모델
            messages=msg,
            temperature=0,
            response_format={ "type": "json_object" },
            timeout=4
        )
        import json
        data = json.loads(r.choices[0].message.content)
        label = data.get("label","other")
        conf = float(data.get("confidence", 0.5))
        return IntentResult(Intent(label), conf, "llm")
    except Exception:
        return IntentResult(Intent.OTHER, 0.3, "llm_error")

# 최종 결정기(스코어 집계)
def detect_intent(text: str, has_file: bool=False) -> IntentResult:
    rule_res = rule_based_intent(text, has_file)

    # 규칙 스코어가 충분하면 그대로 채택
    if rule_res.confidence >= 0.80:
        return rule_res

    # 규칙 신호가 약하면 소형 LLM으로 보강
    if ALLOW_LLM:
        llm_res = llm_fallback(text)
        # 간단한 앙상블: 더 자신 있는 쪽, 또는 편집/생성 우선
        return llm_res if llm_res.confidence >= rule_res.confidence else rule_res

    return rule_res
