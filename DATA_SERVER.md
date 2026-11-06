# 에이두 데이터 서버 연결과 전환 상태

운영 API: `https://aiedue.ddns.net/db-pic8/api`

## 현재 보존 정책

새 API는 에이두 데이터 서버의 `prj_pic8_training` 프로젝트에 연결한 전용 SQLite 저장소를 사용합니다. 기존 데이터 서버 프로세스/DB 테이블은 초기화하지 않습니다.

**기존 ChatGPT 신청 DB의 실제 명단·총인원·PIN 검증 정보는 이 저장소에 없습니다.** 공개 상태 API의 `participants: []`, `count: null`은 개인정보 비공개 계약이며 신청이 0건이라는 증거가 아닙니다. 따라서 처음 배포한 새 DB는 `readyForCutover: false`입니다. 실제 이관이 완료되었다고 표시하지 않습니다.

`training/data-api.js`는 페이지 시작 시 새 서버의 `/health`를 확인합니다. 전환 준비가 명시적으로 `true`일 때만 새 서버를 사용하고, 아직 준비되지 않았거나 확인에 실패하면 원래 API를 유지합니다. 신청/관리 페이지는 같은 선택기를 사용합니다. POST를 다른 서버에 자동 재시도하지 않습니다. 새 서버의 정상 형식 등록·조회·취소는 전환 전 503으로 차단합니다. 기존 UI·PIN 4자리·개인별 결과 공개 시각은 유지합니다.

기존 서버가 이미 받는 신청을 버리고 빈 DB로 교체하거나, 기존 관리자 비밀번호·신청 PIN을 임의 재설정하지 않습니다. 기존 관리자 로그인은 전환 전까지 기존 서버에서 처리합니다. 새 관리자 비밀번호는 운영자 전용 서버 파일에서만 관리하고 저장소·브라우저 코드에 넣지 않습니다.

## 서버 구성

- 소스: `server/core.py`, `server/api.py`; Python 3.11 이상 표준 라이브러리만 사용.
- systemd 사용자 서비스: `pic8-data.service`, loopback `127.0.0.1:9058`.
- Caddy는 `/db-pic8/*`만 해당 서비스로 전달하고 접두사를 제거합니다. 기존 `/db-api/*`, 정적 사이트, 인증 서비스는 변경하지 않습니다.
- 데이터 위치: 실제 에이두 데이터 서버의 `data/projects/pic8-training/storage/registrations.sqlite`.
- 운영 설정 `config.json`, 최초 관리자 암호 `admin-password.txt`와 DB는 해당 비공개 저장 폴더 안에만 보관합니다. 폴더 0700, 파일 0600. HTTP로 설정/DB를 제공하지 않습니다.
- SQLite WAL, 트랜잭션, 해시된 세션 토큰, PIN별 salt + 서버 pepper + PBKDF2, 요청/본인 식별자별 제한을 사용합니다. 비밀번호·PIN·요청 본문·개인 명단을 HTTP 로그에 남기지 않습니다.
- 공개 Origin 허용 목록: `https://pace33.github.io`, `https://aiedue.ddns.net`, 조회수 모듈을 넣을 원본 `https://learning-webapp-library.lejinku.chatgpt.site`. 임의 Origin은 403, OPTIONS는 필요한 메서드/헤더만 허용합니다.

## API 계약

- `GET /api/health`, `GET /api/registrations`: `capacity=20`, `participants=[]`, `count=null`, `published`, `announcementAt`, `readyForCutover`. 개인 명단·총인원 비공개.
- `POST /api/registrations`: `{action: register|lookup|cancel, region, school, name, pin, id?}`. PIN은 ASCII 숫자 4자리. 본인 응답 이름은 마스킹. 취소는 올바른 정보/PIN 및 제공 시 해당 ID가 일치해야 합니다. 중복 동일 신청/PIN은 기존 ID 반환, 다른 PIN은 충돌. 취소 후 재신청은 새 접수순번.
- `POST /api/admin/login {password}` → `{accessToken}`, `DELETE /api/admin/login` 로그아웃 및 세션 폐기.
- `GET /api/manage` Bearer 인증 → `{participants,totalCount,selectedCount,capacity}`. `created_at`은 기존 JS `Intl.DateTimeFormat.format()`와 호환되는 epoch **밀리초 정수**입니다. PIN/해시/salt는 관리자 명단에도 반환하지 않습니다.
- `POST /api/manage {id,selected}`: `selected`는 JSON boolean. 접수 건수에는 정원 제한이 없고 선정만 최대 20명. 트랜잭션/고유 슬롯으로 동시 요청에도 21번째 선정을 거절합니다.
- 한국시간 `2026-11-17T00:00:00+09:00` 전에는 본인 조회에도 선정 여부를 숨깁니다.
- `GET/POST /api/resource-views/{id}`: 실제 SQLite 공유 집계, 원자적 +1. ID `[a-zA-Z0-9_-]{1,100}`. 별도 원본 UI 연결은 `RESOURCE_VIEWS.md` 참조.

## 데이터 보존 전환 절차 — 자동으로 실행하지 않음

1. 원래 백엔드 담당자가 **기존 서버 쓰기를 중지/점검 상태로 전환**하고 일관된 비공개 백업을 내보냅니다. 기존 페이지를 열어 둔 사용자가 옛 서버에 계속 쓰지 못하게 해야 합니다.
2. 관리자 명단 조회만으로는 충분하지 않습니다. 기존 ID·지역·학교·성명·접수순서·시간·선정 슬롯과 **기존 PIN 검증 호환 정보**가 필요합니다. 기존 백엔드 소스/DB에서 PIN 저장 방식을 확인해야 하며, 알 수 없는 해시를 지원한다고 가정하지 않습니다.
3. 현재 가져오기 명령은 아래 명시적 형식을 지원합니다. 실제 PIN이 없는 관리자 공개/조회 목록을 넣으면 실패하고 아무 데이터도 쓰지 않습니다. 기존 해시만 있는 경우 이관 전에 해당 알고리즘의 검증 어댑터를 추가·검증해야 합니다. PIN을 임의 변경하거나 채팅/공개 GitHub에 올리지 마세요.

```json
{"event":"teacher-workshop-jingu-2026","confirmedComplete":true,"sourceRowCount":1,"participants":[{"id":"example-only","region":"충북","school":"예시학교","full_name":"예시명","pin":"9876","receipt_order":1,"created_at":1790000000000,"selected_slot":null}]}
```

4. 백업을 운영자 전용 0600 파일로 전달한 뒤, 소스 홈의 `api.py --home <비공개 데이터 폴더> import --input <백업>`을 실행합니다. 입력 전체 검증과 단일 트랜잭션을 사용하며, 기존/활성 데이터가 있으면 덮어쓰지 않고 거절합니다. 동일 ID·순서·선정 슬롯을 보존합니다. 이 단계만으로 접수를 전환하지 않습니다.
5. 원본/이관 건수·ID·선정 건수와 기존 PIN 조회를 대조한 후 `api.py --home <폴더> activate --legacy-writes-stopped`를 실행합니다. 원래 신청이 실제로 0건이라고 운영자가 확인한 경우에만 `--confirmed-empty --legacy-writes-stopped`로 시작할 수 있습니다. 공개 상태의 빈 배열만 보고 이 옵션을 사용하지 마세요.
6. 사용자 페이지를 새로고침하면 새 서버를 선택합니다. 예전 탭/캐시도 옛 서버에 쓰지 못하도록 1번의 쓰기 중지를 유지합니다. 활성화 후에는 기본 경로의 legacy fallback을 제거하는 마무리 반영도 권장합니다. 이관이 끝난 실제 데이터가 있다면 원본 서버로 단순 되돌리지 말고 새 신청까지 포함한 대사/백업 후 롤백을 판단합니다.

관리자 비밀번호 변경은 서버에서 `set-password` 명령의 비표시 프롬프트로만 입력하고 이 전용 서비스만 재시작합니다. `backup --input <새 비공개 파일>`은 SQLite backup API를 사용합니다. 재배포로 설정·비밀·DB를 재생성하지 않습니다.

## 검증 경계

`python -B -m unittest discover -s server -p test_api.py -v`는 격리된 임시 DB에서 전후 발표 시각, 인증/로그아웃, PIN, 중복/취소, 이관 실패의 무변경, 선정 20명 동시성, 조회수 원자성을 검사합니다. 실제 요청 데이터/비밀번호를 테스트에 사용하지 않습니다.

운영 HTTPS 검증은 일시적으로 활성화한 **별도 `qa.sqlite`**를 사용하는 운영자 비밀 헤더로 수행합니다. API/핸들러는 동일하지만 생산 신청 DB와 명단/선정 슬롯을 공유하지 않습니다. 테스트 후 QA를 끄고 그 테스트 DB만 정리합니다. 이 검증은 기존 실제 신청의 이관 또는 기존 관리자 계정 인증 성공을 의미하지 않습니다. 최종 완료에는 위 원본 백업/0건 확인 절차가 별도로 필요합니다.
