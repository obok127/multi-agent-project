# Mini Carrot - AI Chat Agent with Image Generation & Editing

FastAPI와 Google ADK(Agent Development Kit)를 사용한 AI 채팅 에이전트입니다. 사용자와의 대화를 통해 이미지 생성, 편집, 분석 등 다양한 AI 기능을 제공합니다.

## 주요 기능

- **AI 채팅**: Google Gemini 2.0 Flash 기반 자연어 대화
- **이미지 생성**: OpenAI DALL-E 3를 통한 프롬프트 기반 이미지 생성
- **이미지 편집**: 업로드된 이미지의 편집 및 변형
- **이미지 분석**: 업로드된 이미지의 내용 분석 및 설명
- **의도 감지**: 레이어드 분류기를 통한 사용자 의도 자동 감지
- **세션 관리**: 사용자별 대화 세션 및 이름 기억 기능
- **실시간 UI**: 반응형 채팅 인터페이스
- **이미지 저장**: 생성된 이미지의 자동 다운로드 기능

## 기술 스택

- **Backend**: FastAPI, Python 3.12
- **AI Agent**: Google ADK (Agent Development Kit) - 200% 활용
- **LLM**: Google Gemini 2.0 Flash
- **이미지 생성/편집**: OpenAI DALL-E 3
- **데이터베이스**: SQLite
- **Frontend**: HTML, CSS, JavaScript
- **이미지 처리**: Canvas API, FileReader API

## 프로젝트 구조

```
mini-carrot/
├── app/
│   ├── main.py                    # FastAPI 애플리케이션 진입점
│   ├── chat_service.py            # 채팅 비즈니스 로직 서비스 (ADK 통합)
│   ├── routers/                   # API 라우터들
│   │   ├── chat.py               # 채팅 관련 엔드포인트 (이미지 업로드 지원)
│   │   └── agent.py              # ADK 에이전트 엔드포인트
│   ├── services/                  # 비즈니스 로직 서비스들
│   │   └── image_request.py      # 이미지 요청 처리 서비스
│   ├── intents.py                # 의도 감지 모듈 (레이어드 분류기)
│   ├── adk_agent.py              # ADK 에이전트 설정 및 도구 정의 (200% 활용)
│   ├── tools.py                  # 이미지 생성/편집/분석 도구 (7개 도구)
│   ├── database.py               # 데이터베이스 관리
│   ├── prompts.py                # LLM 프롬프트 정의
│   ├── schemas.py                # Pydantic 데이터 모델
│   ├── frontend/
│   │   └── index.html            # 메인 채팅 인터페이스 (이미지 업로드 UI)
│   ├── static/
│   │   ├── outputs/              # 생성된 이미지 저장소
│   │   └── uploads/              # 업로드된 이미지 저장소
│   └── carrot.db                 # SQLite 데이터베이스
├── requirements.txt              # Python 의존성
├── .gitignore                   # Git 무시 파일
└── README.md                    # 프로젝트 문서
```

## 설치 및 실행

### 1. 환경 설정

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일을 생성하고 다음 변수들을 설정하세요:

```env
OPENAI_API_KEY=your_openai_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
```

### 3. 서버 실행

```bash
# 가상환경 활성화 후
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000`으로 접속하세요.

## API 엔드포인트

### 채팅 API (`/chat`)
- `POST /chat/` - 사용자 메시지 처리 및 AI 응답 (이미지 업로드 지원)
- `POST /chat/api/user/save` - 사용자 정보 저장
- `GET /chat/api/chat/sessions/{user_name}` - 사용자별 세션 조회
- `DELETE /chat/api/chat/sessions/{session_id}` - 세션 삭제

### ADK 에이전트 API (`/api/agent`)
- `POST /api/agent/` - ADK 에이전트를 통한 이미지 생성/편집/분석

### 정적 파일
- `GET /` - 메인 채팅 인터페이스
- `GET /static/outputs/{filename}` - 생성된 이미지 조회
- `GET /static/uploads/{filename}` - 업로드된 이미지 조회
- `GET /health` - 헬스 체크

## 아키텍처 개요

### 의도 감지 시스템
레이어드 분류기를 통해 사용자 의도를 자동으로 감지합니다:

1. **규칙 기반 분류**: 키워드 패턴 매칭
2. **LLM 폴백**: 소형 모델을 통한 복잡한 의도 분석
3. **신뢰도 기반 결정**: 두 방법의 결과를 신뢰도로 비교

### 지원하는 의도
- `IMAGE_GENERATE`: 이미지 생성
- `IMAGE_EDIT`: 이미지 편집 (업로드된 이미지 기반)
- `IMAGE_VARIANT`: 이미지 변형
- `IMAGE_ANALYZE`: 이미지 분석 및 설명
- `CHITCHAT`: 일반 대화
- `HELP`: 도움 요청
- `OTHER`: 기타

### 코드 구조
- **라우터 레이어**: HTTP 요청/응답 처리
- **서비스 레이어**: 비즈니스 로직 처리
- **모델 레이어**: 데이터 구조 및 데이터베이스 조작
- **도구 레이어**: 외부 API 호출 및 유틸리티 함수

## 이미지 기능

### 이미지 생성
- **모델**: OpenAI DALL-E 3
- **기본 크기**: 1024x1024
- **저장 위치**: `app/static/outputs/`
- **지원 형식**: PNG
- **프롬프트 생성**: ADK Agent가 사용자 대화를 분석하여 상세한 영어 프롬프트 생성

### 이미지 편집
- **업로드 지원**: 최대 1개 이미지 파일 업로드
- **지원 형식**: JPG, PNG, GIF 등 모든 이미지 형식
- **저장 위치**: `app/static/uploads/`
- **편집 도구**: ADK Agent의 `edit_image_tool` 사용

### 이미지 분석
- **내용 분석**: 업로드된 이미지의 객체, 색상, 배경 등 분석
- **번역 지원**: 분석 결과를 다양한 언어로 번역
- **분석 도구**: ADK Agent의 `analyze_image_tool` 사용

### 이미지 저장
- **자동 다운로드**: 생성된 이미지의 자동 PNG 다운로드
- **파일명**: `carat-image-{타임스탬프}.png`
- **사용자 피드백**: 저장 완료 시 시각적 알림

### 안전성
- **NPE 방지**: 다층 방어 시스템
  - ImageRequestInfo 데이터클래스로 None 반환 방지
  - 호출부에서 가드 및 폴백 로직
  - 구조화된 로깅으로 디버깅 지원

## 데이터베이스 스키마

### Users 테이블
- `id`: 사용자 고유 ID
- `name`: 사용자 이름
- `created_at`: 생성 시간

### ChatSessions 테이블
- `id`: 세션 고유 ID
- `user_id`: 사용자 ID
- `title`: 세션 제목
- `created_at`: 생성 시간

### Messages 테이블
- `id`: 메시지 고유 ID
- `session_id`: 세션 ID
- `role`: 메시지 역할 (user/assistant)
- `content`: 메시지 내용
- `created_at`: 생성 시간

## 개발 가이드

### 새로운 도구 추가
1. `app/tools.py`에 도구 함수 정의
2. `app/adk_agent.py`에 도구 등록
3. `app/intents.py`에 의도 감지 규칙 추가

### 새로운 API 엔드포인트 추가
1. `app/routers/` 디렉토리에 새로운 라우터 파일 생성
2. `app/main.py`에서 라우터 등록
3. 필요시 `app/services/`에 비즈니스 로직 추가

### 프론트엔드 수정
- `app/frontend/index.html` 파일을 수정하여 UI 변경

### 데이터베이스 변경
- `app/database.py`에서 스키마 수정 후 마이그레이션 실행

### 코드 구조 원칙
- **라우터**: HTTP 요청/응답 처리만 담당
- **서비스**: 비즈니스 로직 처리
- **모델**: 데이터 구조 및 데이터베이스 조작
- **도구**: 외부 API 호출 및 유틸리티 함수

## 주의사항

- OpenAI API 키와 Google API 키가 필요합니다
- 이미지 생성에는 API 비용이 발생할 수 있습니다
- 생성된 이미지는 로컬에 저장되므로 디스크 공간을 확인하세요
- 프로덕션 환경에서는 보안 설정을 추가하세요

## 성능 및 안정성

### 로깅
- 구조화된 로깅으로 디버깅 및 모니터링 지원
- 각 단계별 상세한 로그 기록

### 오류 처리
- 다층 방어 시스템으로 NPE 방지
- 적절한 폴백 메커니즘 제공
- 사용자 친화적인 오류 메시지

### 확장성
- 모듈화된 구조로 새로운 기능 추가 용이
- 라우터/서비스 분리로 유지보수성 향상

## 라이선스

이 프로젝트는 교육 및 개발 목적으로 제작되었습니다.