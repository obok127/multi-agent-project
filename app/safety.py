import re


PROHIBITED_PATTERNS = [
    r"방화", r"방\/?화",
    r"폭탄", r"폭발물", r"폭발",
    r"테러",
    r"살인", r"폭행", r"납치",
    r"총기", r"무기\s*제작", r"폭발물\s*제작",
    r"자살", r"자해",
]


def detect_prohibited(user_text: str) -> str | None:
    """금지 주제 감지: 폭력/불법 행위 조장·미화 요청 등.
    금지 시 사유 문자열을 반환, 아니면 None.
    """
    text = user_text or ""
    for pat in PROHIBITED_PATTERNS:
        try:
            if re.search(pat, text, re.IGNORECASE):
                return "폭력·불법 행위를 조장/미화하는 요청"
        except re.error:
            # 패턴 에러는 무시
            continue
    return None


