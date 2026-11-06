# 에이두 데이터 서버 연결과 전환 상태

운영 API: `https://aiedue.ddns.net/db-pic8/api`

## 현재 운영 경계 — 과거 신청 이관 없이 새 접수

사용자의 명시적 승인으로 운영 모드는 `fresh-start-without-legacy-import`입니다. 새 API는 에이두 데이터 서버의 `prj_pic8_training` 프로젝트 전용 SQLite를 사용합니다. **기존 대상 DB의 신청·선정·ID·접수순서·PIN 검증 정보와 관리자 인증은 보존**하며 재배포나 활성화로 초기화하지 않습니다.

**과거 ChatGPT 서버 신청은 원본에 그대로 남아 있으며 이관하지 않았습니다.** 원본의 데이터·인증·설정은 변경하지 않습니다. 원본 운영 쓰기 제어권이 없으므로 예전 사이트/열린 탭의 원본 쓰기를 막았다고 주장하지 않습니다. 공개 `participants: []`, `count: null`은 비공개 정책이지 원본 0건 확인이 아닙니다. 원본 접근/쓰기 동결은 이 승인된 새 접수 운영의 선행조건이 아닙니다.

`training/data-api.js`는 신청·본인조회·취소·관리자 로그인/명단/선정/개별삭제 모두 **에이두 API만** 반환합니다. 상태 점검 실패·503·네트워크 장애에도 원본 서버로 돌아가지 않으며 실패한 POST를 자동 재전송하지 않습니다. 신청 페이지는 에이두의 `readyForCutover === true`일 때만 제출을 켜고, 장애/준비 중에는 연결 안내와 비활성 버튼을 표시합니다. 캐시를 비운 새 프런트/새로고침부터 이 경계가 적용되며 이미 열린 옛 페이지를 통제한다는 뜻은 아닙니다.

관리자 비밀번호는 기존 에이두 서버의 운영자 전용 파일/설정 그대로 유지하며 공개 저장소·브라우저 코드에 넣지 않습니다. 원본 서버의 관리자 계정/PIN과 에이두 계정이 통합되었다고 주장하지 않습니다. 숫자 ASCII PIN 4자리·정원·개인정보 비공개·결과 공개 시각도 유지합니다.

## 승인된 새 접수 활성화 — 로컬 운영자 전용

1. 실행 중인 `pic8-data.service`의 실제 runtime/홈/9058 loopback을 확인하고 SQLite backup API로 대상 DB의 일관 백업을 만듭니다. 설정·기존 암호 파일·runtime 코드·서비스 unit도 비공개 보관하고 무결성과 권한을 확인합니다.
2. 격리 테스트 후 runtime 코드만 최소 배포합니다. 기존 `config.json`, `admin-password.txt`, DB는 덮어쓰거나 `init`/`set-password`로 재생성하지 않습니다.
3. 다음 명시적 명령으로 활성화합니다. 원본 0건/원본 쓰기 차단 확인 플래그를 대신 쓰지 않습니다.

```sh
python3 -B api.py --home '<기존 비공개 데이터 폴더>' fresh-start --user-authorized-fresh-start
```

4. 단일 SQLite 트랜잭션이 `active=1`, `operationMode=fresh-start-without-legacy-import`, `sourceNotImported=1`, `legacyWritesNotControlled=1`, `userAuthorizedFreshStart=1`, `legacyDataMigrated=0`, `legacyWritesStopped=0`, 최초 활성화 UTC 시각·당시 대상 건수를 감사 메타데이터로 남깁니다. 신청/선정/접수순번/세션/조회수/PIN/관리자 설정은 변경하지 않습니다. 재실행은 최초 감사 시각을 보존합니다. 기존 이관 메타데이터나 다른 활성 운영이 있으면 거절하여 과거 사실을 재분류하지 않습니다.
5. 이 전용 서비스만 재시작하고 health의 준비 상태/운영 모드, 기존 암호 실제 로그인, 테스트 ID별 기능·재시작 저장 보존을 검증합니다. 테스트 신청만 정확한 ID로 정리합니다. 새 실제 신청이 생기면 그대로 보존하며 전체 DB 복원/초기화로 QA 오류를 해결하지 않습니다.
6. GitHub main/Pages 배포 후 신청/관리 HTML·JS의 커밋 바이트와 버전 체인, 브라우저의 에이두 단일 API 사용을 확인합니다. `cutoverComplete`는 **새 접수 경로 전환 완료**이며 과거 데이터 이관/원본 쓰기 차단 완료를 의미하지 않습니다.

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
- `DELETE /api/manage {id,confirmed:true}`: 관리자 인증과 명시적 삭제 확인이 필요합니다. 해당 신청 1건을 삭제하며 선정 슬롯도 비워집니다. 삭제된 신청은 본인 조회에 표시되지 않고 재신청할 수 있습니다.
- 한국시간 `2026-11-17T00:00:00+09:00` 전에는 본인 조회에도 선정 여부를 숨깁니다.
- `GET/POST /api/resource-views/{id}`: 실제 SQLite 공유 집계, 원자적 +1. ID `[a-zA-Z0-9_-]{1,100}`. 별도 원본 UI 연결은 `RESOURCE_VIEWS.md` 참조.

## 별도의 과거 데이터 이관 경로 — 이번 새 접수 운영에는 사용하지 않음

1. 원래 백엔드 담당자가 **기존 서버 쓰기를 중지/점검 상태로 전환**하고 일관된 비공개 백업을 내보냅니다. 기존 페이지를 열어 둔 사용자가 옛 서버에 계속 쓰지 못하게 해야 합니다.
2. 관리자 명단 조회만으로는 충분하지 않습니다. 기존 ID·지역·학교·성명·접수순서·시간·선정 슬롯과 **기존 PIN 검증 호환 정보**가 필요합니다. 기존 백엔드 소스/DB에서 PIN 저장 방식을 확인해야 하며, 알 수 없는 해시를 지원한다고 가정하지 않습니다.
3. 현재 가져오기 명령은 아래 명시적 형식을 지원합니다. 실제 PIN이 없는 관리자 공개/조회 목록을 넣으면 실패하고 아무 데이터도 쓰지 않습니다. 기존 해시만 있는 경우 이관 전에 해당 알고리즘의 검증 어댑터를 추가·검증해야 합니다. PIN을 임의 변경하거나 채팅/공개 GitHub에 올리지 마세요.

```json
{"event":"teacher-workshop-jingu-2026","confirmedComplete":true,"sourceRowCount":1,"participants":[{"id":"example-only","region":"충북","school":"예시학교","full_name":"예시명","pin":"9876","receipt_order":1,"created_at":1790000000000,"selected_slot":null}]}
```

4. 백업을 운영자 전용 0600 파일로 전달한 뒤, 소스 홈의 `api.py --home <비공개 데이터 폴더> import --input <백업>`을 실행합니다. 입력 전체 검증과 단일 트랜잭션을 사용하며, 기존/활성 데이터가 있으면 덮어쓰지 않고 거절합니다. 동일 ID·순서·선정 슬롯을 보존합니다. 이 단계만으로 접수를 전환하지 않습니다.
5. 원본/이관 건수·ID·선정 건수와 기존 PIN 조회를 대조한 후 `api.py --home <폴더> activate --legacy-writes-stopped`를 실행합니다. 원래 신청이 실제로 0건이라고 운영자가 확인한 경우에만 `--confirmed-empty --legacy-writes-stopped`로 시작할 수 있습니다. 공개 상태의 빈 배열만 보고 이 옵션을 사용하지 마세요.
6. 이 경로는 별도의 미활성/빈 대상에만 사용합니다. 현재 새 접수 운영 DB에는 뒤늦게 import하지 않습니다. 향후 합병은 새 접수와 ID/PIN/접수순서 충돌을 대사하는 별도 작업입니다. 프런트는 이미 에이두 단일 경로이며, 그 사실만으로 예전 탭/원본 쓰기가 차단되지는 않습니다. 실제 접수가 있으면 원본으로 단순 되돌리거나 예전 백업으로 DB를 덮어쓰지 말고 새 신청까지 보존한 대사/백업 후 복구를 판단합니다.

관리자 비밀번호 변경은 서버에서 `set-password` 명령의 비표시 프롬프트로만 입력하고 이 전용 서비스만 재시작합니다. `backup --input <새 비공개 파일>`은 SQLite backup API를 사용합니다. 재배포로 설정·비밀·DB를 재생성하지 않습니다.

## 검증 경계

`python -B -m unittest discover -s server -p 'test_*.py' -v`는 격리된 임시 DB에서 발표 1ms 전/정각, 인증/로그아웃, ASCII PIN, 중복/취소/개별삭제, 기존 이관 실패의 무변경, 선정 20명 동시성, 조회수 원자성 및 새 운영 CLI의 승인/감사/기존 데이터·인증 보존/재실행을 검사합니다. `node server/test-routing.mjs`는 에이두 단일 경로, inactive/503/잘못된 JSON/네트워크 실패의 버튼 상태, POST 자동 재전송 금지, 관리자 장애 복구와 HTML 버전 체인을 검사합니다. 실제 요청 데이터/비밀번호를 공개 테스트에 사용하지 않습니다.

운영 HTTPS 검증은 이번 승인에 따라 **실제 대상 DB의 고유 표식 테스트 신청만** 사용합니다. 기존 암호로 실제 로그인하고 등록→본인조회→선정→취소 및 별도 ID의 개별삭제를 확인합니다. 전용 서비스 재시작 전후 동일 ID/저장/세션 보존을 확인하고 테스트 ID만 정리합니다. 다른 실제 신청/선정에는 손대지 않습니다. 테스트 자격/ID/관리 명단/원시 로그는 비공개 증적에만 저장합니다. 정원 20명/발표 시각 경계는 격리 DB에서 검증하고 운영 DB의 실제 선정 인원을 QA로 채우지 않습니다. `qa_enabled` 등 기존 운영 설정도 바꾸지 않습니다. 운영 검증은 과거 신청/PIN 이관 또는 원본 계정 통합 성공을 뜻하지 않습니다.
