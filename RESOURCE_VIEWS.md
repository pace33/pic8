# 메인 자료실 · 공유 조회수

메인 `index.html`은 자체 UI이며 외부 앱 redirect/iframe이 아닙니다.
목록/등록/수정/삭제/설정은 `https://aiedue.ddns.net/db-pic8/api`를 사용합니다.
자료 스키마·인증 경계·원본 인증 미확인 사항은 `MAIN_LIBRARY.md`를 참고하세요.

## 새 메인 자료실

- `GET /api/resources`에서 서버 공유 조회수와 자료 목록을 함께 읽습니다.
- 자료 열기: `PATCH /api/resources {"id":"서버 자료 ID"}`. 실제 자료 ID에만 +1하며 SQLite에서 원자적으로 증가합니다.
- 서버 응답에 성공한 경우에만 UI 수치를 바꿉니다. localStorage 수치를 서버 조회수처럼 표시하지 않습니다.
- 원본 자료와 원본 조회수는 이관하지 않았습니다. 원본 레코드에 대한 쓰기도 하지 않았습니다.

## 기존 호환 엔드포인트

- `GET /api/resource-views` → `{views:{resourceId:count}}`.
- `POST /api/resource-views {"resourceId":"example"}` → `{resourceId,views}`.
- 이는 기존 독립 카운터로 계속 보존합니다. 새 `library.sqlite` 자료 조회수와 합산하거나 기존 값을 초기화하지 않습니다.
- 저장 위치: `/home/aiedue/.local/share/pic8-data/registrations.sqlite`의 `resource_views` 테이블.
- 실패 시 원본이나 타 서버로 fallback하지 않습니다.
