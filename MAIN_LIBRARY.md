# 자체 메인 자료실 — 에이두 저장소 연결

메인 `index.html`은 이제 외부 GPT 앱으로 이동하거나 iframe을 표시하지 않습니다.
`library.js`와 `library.css`로 동일한 공개 화면/등록/검색/과목필터/정렬/수정/삭제/제목 설정을 자체 실행합니다.
API는 항상 `https://aiedue.ddns.net/db-pic8/api`입니다. 실패 시 원본으로 돌아가지 않으며 쓰기를 자동 재시도하지 않습니다.

## 데이터와 권한 경계

- `server/library.py`는 기존 training DB와 구분된 `library.sqlite`를 사용합니다. `CREATE IF NOT EXISTS`만 사용하며 기존 자료/제목을 초기화하지 않습니다.
- 원본 GPT 자료 16건은 이관/변경/삭제하지 않았습니다. 새 에이두 자료는 최초 활성화 당시 0건부터 시작했으며, 이후 운영 자료를 재배포로 초기화하지 않습니다. 조회수도 원본/localStorage에서 가져오지 않습니다.
- 사용자가 승인한 범위는 **과거 GPT 인증은 이관하지 않았으며 에이두 관리자로 새 운영**입니다. 원본 플랫폼 사용자/계정/인증·권한의 이관 또는 동등성 재현은 이번 새 운영의 필수 조건이 아니며, 원본 서버 소스/인증 계약 접근이나 같은 전환의 재승인을 요구하지 않습니다. 원본 인증의 동등성을 구현·검증했다고 주장하지 않습니다.
- 메인 등록/수정/삭제/제목 변경에는 **기존 에이두 관리자 로그인/세션**을 요구합니다. 이는 원본 플랫폼 계정의 이관/연동이 아닙니다. 비인증 쓰기를 허용하거나 권한을 완화하거나 암호를 임의로 변경하지 않습니다. 공개 읽기 가능 여부만으로 원본 쓰기 권한을 추정하지 않습니다.
- training 비밀번호/설정/신청/선정/PIN/삭제 동작은 그대로 보존합니다. 로그인은 기존 `/api/admin/login`을 재사용합니다. 비밀번호와 토큰은 공개 소스에 없습니다.
- 원본 화면의 문구/색상/레이아웃/SVG를 읽기 전용 참고해 정적 UI를 재구성했습니다. 배포 파일에는 원본 자료 레코드가 없습니다.

## 메인 API

- `GET /api/resources` → `{resources:[...]}`. 필드 `id,title,url,author,description,subject,grade,tags,views,createdBy,createdAt,revision`.
- `tags`는 기존 공개 응답과 같은 JSON 문자열입니다. 입력은 쉼표 문자열/문자열 배열이며 최대 5개, 각 30자입니다.
- 관리자 Bearer 인증: `POST /api/resources` 새 자료, `PUT /api/resources` 수정, `DELETE /api/resources` 삭제.
- 수정은 `{id,revision,...fields}`, 삭제는 `{id,revision,confirmed:true}`를 요구합니다. 버전 불일치는 409로 거부해 동시 변경을 보존합니다. ID/작성시각/작성주체/조회수는 서버가 정합니다.
- `PATCH /api/resources {id}` → SQLite 트랜잭션 공유 조회수 +1. 없는 ID는 404입니다. 실패한 수치를 가상 공용 수치로 표시하지 않습니다.
- `GET /api/settings` → `{title,revision}`. 관리자 `PUT /api/settings {title,revision}`는 compare-and-swap입니다. 임시 QA 제목도 정확한 버전이 일치할 때만 원래 값으로 복구합니다.
- `GET /api/admin/login`은 기존 세션 유효 여부만 확인하며 관리자 명단을 반환하지 않습니다.
- URL은 http/https만, 제목 80자/작성자 40자/설명 300자/사이트 제목 30자입니다. 서버측 유효성 검사·출처 허용목록·빈도 제한을 적용합니다. 브라우저는 사용자 텍스트를 HTML로 삽입하지 않습니다.

## 배포/검증

정적 파일은 GitHub Pages 및 에이두 `/pic/8/`에서 제공합니다. 후자의 `/training/` 상대 링크도 동일한 저장소 파일을 제공합니다. `/pic/*` 전체 라우트가 아닌 `/pic/8`·`/pic/8/*`만 별도 경로를 둡니다.
운영 변경 전 SQLite backup API 일관 백업, 비공개 설정/서비스/runtime/Caddy 백업과 읽기 재검증이 필요합니다. 신규 모듈을 명시적으로 포함해 격리 Linux 테스트 후 이 전용 `pic8-data.service`만 재시작합니다. Caddy는 관련 경로만 검증·hot-load하며 다른 서비스는 재시작하지 않습니다.

`python -B -m unittest discover -s server -p 'test_*.py' -v`와 `node server/test-routing.mjs`를 실행합니다. API/권한/CORS/경합/재초기화 보존과 기존 training 회귀를 포함합니다. 실제 배포 여부는 public GET 바이트와 Git blob 일치로, 실제 사용은 브라우저 CRUD·공유 조회수·제목 복구·서비스 재시작 후 같은 레코드/세션 보존으로 별도 검증합니다. 테스트 레코드는 고유 ID만 삭제합니다.
