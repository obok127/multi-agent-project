# Mini Carat – 이미지 생성/편집 AI 채팅 에이전트

FastAPI + OpenAI + SQLite로 동작하는 한국어 AI 채팅 앱입니다. “2-턴(Clarify-Once) 대화”로 필요한 정보만 한 번 묻고 바로 이미지(생성/편집)를 수행합니다. 프론트엔드는 단일 `index.html` 기반으로 모달 편집기(브러시 선택)까지 제공합니다.

## 빠른 시작(클론 → 실행)

```bash
git clone https://github.com/obok127/mini-carat-image-agent.git
cd mini-carat-image-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env 작성 후 실행 (포트 8001)
python -m uvicorn app.main:app --env-file .env --reload --host 0.0.0.0 --port 8001
```

브라우저: `http://localhost:8001`

## 주요 기능

- 대화 라우팅(LLM Router): `generate | edit | chat` 의도 분류 및 슬롯 추출(객체/스타일/포즈/배경)
- Clarify-Once: 정보 부족 시 한 번만 친절한 질문(이모지 포함 템플릿), 이후 바로 실행
- 이미지 생성: OpenAI DALL·E 3 사용, 결과는 확인 멘트 → 완료 pill → 이미지 → 캡션 → 요약 순서로 표시
- 이미지 편집(선택 영역): 프론트에서 칠한 마스크를 서버에서 알파 마스크로 변환 후 DALL·E 2 편집(REST)
- 다시 생성(품질 강화): 기존 프롬프트를 1문장 내로 품질 힌트(2~3개)만 보강해 재생성
- 세션/기록: 사용자/세션/메시지 SQLite 저장, 사이드바에 이전 대화 목록 표시, 세션 제목은 LLM이 생성(6~14자 명사형)
- UI/UX: 고정 사이드바/탑바, 말풍선 좌측 정렬, “이미지 생성 중…” 인디케이터, 이미지 카드 540px, 토글 모달 너비 입력창과 동일(최대 960px)
- 공유: 대화 내용을 마크다운으로 다운로드(Share)

## 기술 스택

- Backend: FastAPI, Python 3.11+
- LLM: OpenAI(gpt-4o-mini) – 라우터/제목/프롬프트 리라이트, (키 없을 시) Gemini 폴백
- 이미지: 생성 DALL·E 3, 편집 DALL·E 2(REST, PNG 강제)
- DB: SQLite (`app/carrot.db`)
- FE: HTML/CSS/JS (단일 파일 UI)
- 이미지 처리: Pillow, NumPy (선택 썸네일 → 알파 마스크)

## 디렉터리 구조

```
mini-carrot/
├── app/
│   ├── main.py                # FastAPI 엔트리(정적 서빙, /chat API 등)
│   ├── orchestrator.py        # 2-턴 오케스트레이션(Clarify-Once, 실행)
│   ├── router.py              # LLM 기반 intent 라우터/슬롯 추출
│   ├── prompts.py             # 시스템 프롬프트/템플릿(Clarify/Title/Edit/Regenerate 등)
│   ├── tools.py               # 이미지 생성/편집 도구(DALL·E3/DALL·E2, PNG 변환)
│   ├── database.py            # SQLite 초기화/CRUD(Users, Sessions, Messages, Onboarding)
│   ├── session_manager.py     # 세션 컨텍스트(쿠키 sid) 관리
│   ├── onboarding_service.py  # 이름 추출·온보딩 처리
│   ├── error_handler.py       # 예외 → 사용자 메시지 매핑
│   ├── settings.py            # 환경변수 로딩
│   ├── ui/
│   │   └── index.html         # 단일 프론트엔드(채팅/모달 편집기/사이드바/공유)
│   └── static/
│       └── outputs/           # 생성/편집된 파일 저장(정적 서빙)
├── requirements.txt
└── README.md
```

## 핵심 파일 설명

- main.py: FastAPI 진입점. 정적 서빙(/static), INDEX_PATH(App UI), API 라우트.
- orchestrator.py: 대화 오케스트레이션(Clarify-Once, fast-path, ADK 경유, 실행/저장).
- tools.py: 이미지 생성(DALL·E3 또는 Azure 배포), 편집(DALL·E2 REST) 유틸.
- adk.py: ADK 에이전트 정의/실행 래퍼(실패 시 로컬 툴 폴백).
- router.py: LLM 라우터(생성/편집/채팅 의도 분기).
- prompts.py: 시스템 프롬프트/템플릿(Clarify/Title/Edit/Regenerate/Chat).
- settings.py: .env 로딩(OPENAI/Azure 설정, 프론트 ORIGIN 등).
- database.py: SQLite 초기화/CRUD(사용자, 세션, 메시지).
- session_manager.py: 세션 컨텍스트(쿠키 sid) 관리.
- onboarding_service.py: 이름 추출/온보딩 상태 처리.
- error_handler.py: 예외 → 사용자 메시지/로그 매핑.

## 설치 및 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 환경변수(.env) 준비 후 실행 (포트 8001 권장)
python -m uvicorn app.main:app --env-file .env --reload --host 0.0.0.0 --port 8001
```

브라우저: `http://localhost:8001`

## 환경 변수(.env)

```env
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
ROUTER_MODEL=gpt-4o-mini
ADK_MODEL=gemini-2.0-flash-8b
FRONT_ORIGIN=http://localhost:5173
USE_ADK=true
ADK_TIMEOUT=25
```

참고: 편집은 `dall-e-2` REST를 사용합니다.

## ADK(Agent Development Kit) 통합

- 오케스트레이션: ADK 우선 → 실패 시 로컬 툴 폴백
  - `app/orchestrator.py`는 JSON 태스크를 만들고 `app.adk.adk_run(task_json, timeout)`을 호출합니다.
  - `app/adk.py`의 `adk_run()`은 에이전트의 `invoke/run/execute` 메서드를 자동 탐지해 실행하고, 실패 시 JSON을 파싱하여 로컬 도구(`generate_image_tool`/`edit_image_tool`)로 안전하게 처리합니다.
- 환경변수
  - `USE_ADK=true|false`(기본 true): ADK 사용 토글
  - `ADK_TIMEOUT=초`(기본 25): ADK 실행 제한 시간
- 경로 이슈 대응: 일부 실행 컨텍스트에서 패키지 경로 문제가 생길 수 있어, `app/adk.py`는 import 실패 시 `sys.path`를 보정하여 `app.tools`를 확실히 불러옵니다.

## 문제 해결(Troubleshooting)

- ADK 에러: `'LlmAgent' object has no attribute 'run'`
  - 해결: `.env`에서 `USE_ADK=false`로 폴백 사용(기능 정상). ADK 환경 준비 후 `USE_ADK=true`로 재시도.
  - 참고: `app/adk.py`의 `adk_run()`이 `invoke/run/execute`를 자동 탐지해 호출하며, 모두 실패 시 로컬 툴로 안전 폴백합니다.

- `ModuleNotFoundError: No module named 'app'`
  - 해결: 프로젝트 루트에서 실행(`uvicorn app.main:app ...`). `app/adk.py`가 경로 보정(fallback)을 포함하지만, 루트 실행이 가장 안전합니다.

- CORS/쿠키로 세션이 유지되지 않음
  - `.env`의 `FRONT_ORIGIN`이 브라우저 접속 도메인과 일치해야 쿠키가 전송됩니다. 단일 서버 사용 시 `http://localhost:8001` 권장.

- favicon/apple-touch-icon 404
  - 기능과 무관. 무시해도 됩니다.

## API 엔드포인트(백엔드)

- POST /chat
  - FormData: `message`, `user_name`, `session_id`, `images[]?`, `selection?`, `image_path?`
  - 동작: 라우팅 → 필요 시 Clarify-Once → 생성/편집 실행 → `{ reply, url?, meta }`
- POST /chat/api/user/save – 사용자 저장(이름)
- GET /chat/api/chat/sessions/{user_name} – 사용자별 세션 목록
- DELETE /chat/api/chat/sessions/{session_id} – 세션 삭제
- GET /chat/api/chat/sessions/{session_id}/messages – 세션 메시지 목록
- GET / – 프론트 `index.html`
- GET /static/... – 정적 파일(생성 결과)
- GET /health – 헬스 체크

## 동작 개요

- 기본 스타일/분위기: illustration + cute(따뜻한 톤 포함)
- Clarify-Once: 부족 슬롯(스타일/포즈/배경 등)만 한 번 묻고 즉시 실행
- 생성 결과 UI: 확인 멘트(말풍선) → 완료 pill → 이미지 카드(540px) → 캡션(작은 회색 글씨) → 최종 요약(말풍선)
- 편집(선택 영역):
  1) 이미지 카드의 “선택 수정” → 모달 오픈
  2) 검정 브러시(65% 투명)로 영역 칠하기(지우기/반전/브러시 크기)
  3) “선택 부분만 수정” → `selection.png` + 원본 URL을 서버로 업로드
  4) 서버에서 선택 썸네일 → 알파 마스크(PNG) 변환 → `dall-e-2` 편집 호출 → 결과 반영
- 다시 생성: 기존 프롬프트에 2~3개의 품질 힌트만 추가해 재생성
- 세션: 쿠키 `sid` + DB 세션 ID로 지속, 제목은 LLM 생성(6~14자, 명사형)

## 프론트엔드(UI)

- 고정 사이드바/탑바, 메인 스크롤 영역 분리
- 말풍선/캡션 좌측 정렬, 이미지 카드 너비 540px
- 일반 타이핑(...)과 이미지 전용 “이미지 생성 중…” 인디케이터 분리
- 사이드바에서 세션 목록 로드/삭제, “공유하기”로 마크다운 저장
- 토글 모달(플러스/설정/별 버튼) 너비를 입력창과 동일(최대 960px)로 맞춤

## 데이터베이스 스키마

### users
- `id`, `name`, `created_at`, `last_visit`

### chat_sessions
- `id`, `user_id`, `title`, `created_at`, `updated_at`, `onboarding_*`, `user_name`

### messages
- `id`, `session_id`, `role`, `content`, `created_at`

### onboarding_states
- `session_name`, `greeted`, `asked_once`, `user_name`, `created_at`, `updated_at`

## 프롬프트/정책

- ASK_CLARIFY_SYSTEM_PROMPT: 친절한 한국어 Clarify-Once 템플릿(이모지/예시 포함)
- EDIT_PROMPT_SYSTEM: 한국어 편집 지시문 → 간결한 영어(1~2문장) 프롬프트 변환
- REGENERATE_PROMPT_SYSTEM: 품질 강화 힌트(2~3개)만 덧붙여 1문장 유지
- TITLE_PROMPT_SYSTEM: 6~14자, 명사형, 이모지·문장부호 금지

## 에러 처리/제약

- 편집은 `dall-e-2`(REST) 사용
- 편집 업로드는 PNG 필요 → 서버에서 PNG 변환/업로드 강제
- 네트워크/쿼터/모델 오류는 사용자 친화 메시지로 매핑(`error_handler.py`)

## 사용 예

1) “고양이 사진 생성” → (필요 시) Clarify-Once 질문 1회 → 생성 진행
2) 결과 카드의 “선택 수정” → 영역 칠하기 → 지시문 입력 → 편집 결과 표시
3) “다시 생성” 버튼으로 품질만 강화한 재생성

## 개발 메모

- CORS: `FRONT_ORIGIN`과 `allow_credentials=True` 설정으로 쿠키 기반 세션 유지
- 파일 경로: `/static/outputs/...`는 `app/static/outputs`에 매핑되어 로컬 서빙
- 라우터: OpenAI 키 없으면 자동으로 Gemini 폴백

---

문의/피드백 환영합니다. 😊
