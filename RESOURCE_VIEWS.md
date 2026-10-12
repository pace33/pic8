# 배움 링크 자료별 조회수 (연동 파일)

이 폴더의 `index.html`은 **외부 웹앱을 iframe으로 표시하는 연결 페이지**입니다.
실제 '필요한 자료' 버튼은 `https://learning-webapp-library.lejinku.chatgpt.site/` 안에 있습니다.
브라우저 보안(다른 출처 iframe) 때문에 **이 GitHub 파일만 수정해 내부 버튼 클릭을 읽을 수는 없습니다.**

## 추가한 코드
`resource-view-counter.js` : 실제 웹앱의 HTML에서 사용할 조회수 표시/클릭 집계 모듈.

### 원본 앱에 붙이는 방법
자료 카드/버튼에 고유 ID를 부여합니다:

```html
<a href="https://example.org/material" data-resource-id="material-001" target="_blank">
  필요한 자료
</a>
<script src="https://aiedue.ddns.net/pic/8/resource-view-counter.js" defer></script>
```

각 자료에 `data-resource-id`를 다르게 지정하면, 버튼 안에 조회수 배지가 자동 표시되며
클릭 시 +1 됩니다. 기본 설정은 해당 브라우저에만 저장하므로
`이 기기 조회수`로 표시됩니다. 웹앱 자체 소스 수정이 필수입니다.

### 전체 방문자에게 같은 조회수 보여주기
백엔드 API가 마련된 경우 다음처럼 사용합니다.

```html
<script src="https://aiedue.ddns.net/pic/8/resource-view-counter.js"
        data-views-api="/api/resource-views" defer></script>
```

API 규약:
- `GET /api/resource-views/{id}` → `{"views": 10}`
- `POST /api/resource-views/{id}` → 서버에서 원자적으로 +1 후 `{"views": 11}`
- ID는 영문·숫자·하이픈·밑줄, 1~100자
- 다른 도메인에 API가 있으면 CORS 및 적절한 남용 방지 설정 필요
- API 실패 시 임의의 조회수를 표시하지 않고 `—` 표시

**주의:** 원본 앱 HTML/JS와 공용 저장 API는 이 GitHub 저장소에 포함돼 있지 않습니다.
원본 코드 연동·백엔드 배포 전에는 요청된 "모든 사람에게 공통 조회수" 기능이 완성되지 않습니다.
