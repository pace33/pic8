# 자료별 공유 조회수 연결

`resource-view-counter.js`의 기본 저장 API는 실제 에이두 데이터 서버의
`https://aiedue.ddns.net/db-pic8/api/resource-views`입니다.
서버 SQLite에서 자료 ID별 GET과 원자적 POST +1을 처리하며, 임의 수치나 기기별 수치를 공용 값처럼 표시하지 않습니다. 실패 배지는 `—`입니다.

```html
<a href="https://example.org/material" data-resource-id="material-001" target="_blank">필요한 자료</a>
<script src="https://pace33.github.io/pic8/resource-view-counter.js"
        data-views-api="https://aiedue.ddns.net/db-pic8/api/resource-views" defer></script>
```

ID는 `[a-zA-Z0-9_-]{1,100}`입니다.
GET `/api/resource-views/{id}` → `{"views":n}`,
POST 같은 경로에 `{}` → 저장된 공유 조회수 +1.
허용 Origin은 서버 설정의 정확한 목록만 사용하고 CORS/OPTIONS 및 요청 빈도를 검사합니다.

## 아직 원본 앱에 필요한 작업

이 저장소의 루트 `index.html`은
`https://learning-webapp-library.lejinku.chatgpt.site/`를 iframe으로 보여 주는 연결 페이지입니다.
실제 자료 버튼과 원본 앱 HTML/JS는 이 저장소에 없습니다.
**부모 iframe 페이지 수정만으로 다른 Origin 내부 클릭을 수집할 수 없습니다.**
원본 앱에 위 모듈과 실제 자료별 `data-resource-id`를 넣어야 하며,
그 작업을 확인하기 전에는 내부 버튼의 공용 조회수 연결 완료로 보고하지 않습니다.
기존 각 기기의 localStorage 조회수는 원본 공용 기록이 아니므로 임의 합산·이관하지 않습니다.

신청/관리 API의 기존 데이터 보존·전환 잠금은 [DATA_SERVER.md](DATA_SERVER.md)를 참조하세요.
