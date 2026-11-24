# SimAsset 결과 검토 시제품

검사 결과 폴더를 검증해 로컬 PostgreSQL에 가져오고, 영상·시계열·측정값을 보면서 사람 판정을 남깁니다. 같은 결과를 다시 가져오면 중복으로 기록하고, 같은 실행 ID의 내용이 다르면 기존 결과를 보존한 채 충돌을 표시합니다.

현재 어댑터는 팀에서 공유한 `incline_env.zip`의 빗면 검사와 `probe_env.zip`의 홈 검사 출력에 맞췄습니다. 팀의 최종 스키마나 판정 규약은 아닙니다. 나머지 검사 출력은 해당 검사에 맞는 검증기를 추가해야 합니다.

## 실행

Python 3.11, uv, PostgreSQL 16 이상이 필요합니다. macOS에서 PostgreSQL 실행 파일이 PATH에 없으면 설치된 PostgreSQL의 `bin`을 먼저 추가합니다. 아래 명령은 이 저장소의 `review` 폴더에서 실행합니다.

```bash
uv sync --locked --extra test --extra benchmark
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"  # Homebrew 설치인 경우
uv run python scripts/local_db.py start
uv run simasset-review init-db
uv run simasset-review serve
```

브라우저에서 [결과 검토 화면](http://127.0.0.1:8765)을 엽니다. 서버는 로컬 주소에만 연결합니다. 로그인·권한 관리·공개 배포가 없는 개인 검토용입니다.

다른 터미널에서 실제 결과 폴더를 가져옵니다. `--namespace`는 결과 제공자·배치의 식별자이고, `--origin`은 팀 공유 원본, 직접 재현, 기능 시험 데이터를 구분합니다.

```bash
uv run simasset-review import /absolute/path/to/result \
  --namespace shared-incline-20261117 --origin team_shared

# 먼저 예상 실행 목록과 폴더·근거 파일을 대조합니다. DB는 필요하지 않습니다.
uv run simasset-review audit /absolute/path/to/result-batch \
  --expected /absolute/path/to/expected.json

# summary.csv뿐 아니라 meta.json·시계열만 남은 불완전한 폴더도 검사합니다.
uv run simasset-review import /absolute/path/to/result-batch \
  --recursive --namespace shared-incline-20261117 --origin team_shared
```

출력의 `imported`, `duplicate`, `conflict`, `invalid`를 확인합니다. 일부가 실패하면 정상 항목은 유지하고 CLI는 종료 코드 2를 반환합니다. 오류를 고친 파일은 다시 가져올 수 있으며, 이전 시도 기록은 남습니다. 내용이 달라진 동일 ID를 강제로 덮어쓰는 옵션은 없습니다.

`audit`의 `valid`는 파일 형식이 유효하다는 뜻입니다. 에셋 품질 통과와 다릅니다. 예상 목록을 생략하면 존재하는 폴더만 검사하므로, 전체 에셋·검사 조합이 모두 제출됐다고 판정하지 않습니다. 예상 목록 형식은 [결과 제출 초안](docs/결과제출_계약초안.md)에 있습니다.

홈 검사에서는 공의 진입 깊이를 별도 그래프로 표시합니다. 공을 놓기 전의 빈 값은 측정값 0으로 바꾸지 않습니다. 원본의 `not_applicable`은 검사 대상 아님으로 보관하며, 이 경로에서 기록되지 않은 에셋 해시도 그대로 미기록으로 표시합니다. `probe_pass`는 코드의 측정 결과로만 저장합니다.

화면에서 실행을 선택하고 영상·그래프·원본 단위를 확인한 뒤 평가자, 검토 항목, 기준 버전, 이유를 입력합니다. 저장 후에도 선택한 항목·기준·근거가 유지됩니다. 기존 판정은 이력의 **이 판정 수정**으로 불러올 수 있으며, 수정 기록은 이전 판정을 참조합니다. 다른 실행으로 이동했다 돌아와도 그 실행의 입력값은 유지되지만, 브라우저 페이지 자체를 새로고침하면 저장하지 않은 입력은 사라집니다. 저장한 내용은 이력에서 다시 불러옵니다. `ok` 같은 자동 상태가 사람의 통과 판정으로 바뀌지는 않습니다.

## 한 화면 검토와 비교

기본 화면은 실행 목록, 영상·핵심 수치·대표 그래프, 판정 입력으로 구성합니다. 데스크톱에서는 화면 높이에 맞춰 배치하고 실행 목록만 따로 스크롤합니다. 기준 버전과 근거 파일은 **기준·근거**를 펼쳐 선택합니다.

- **모아보기**: 같은 실행의 그래프를 함께 표시합니다. 시간축을 맞추고 한 그래프에서 시점을 짚으면 다른 그래프의 관측값도 함께 표시합니다. 서로 다른 지표의 세로축은 각 지표에 맞게 유지합니다.
- **실행 비교**: 같은 검사 종류의 두 실행을 선택해 영상·핵심 수치·같은 지표를 나란히 봅니다. 같은 에셋의 다른 조건을 먼저 제안하며, 실행 ID와 에셋 해시로 결과를 구분합니다. 두 그래프의 가로·세로축 범위는 같습니다.
- 비교 영상은 **함께 재생 / 일시정지**, 공통 시간 막대, **1× / 0.25×**로 조작합니다. 시간 막대는 저장 영상의 재생 초이며 시뮬레이션 관측 시각과 자동 동기화하지 않습니다. 짧은 영상은 마지막 프레임에서 멈춥니다.
- **상세 자료**: 전체 측정값, 판정 이력, 검사 조건과 파일을 엽니다. 비교·상세 창을 닫아도 작성 중인 판정과 근거 선택이 유지됩니다.

작은 화면에서는 비교 결과를 세로로 쌓습니다. 값이 없는 구간과 검사 대상이 아닌 실행은 0이나 불통과로 바꾸지 않습니다.

## 화면 테마

결과 검토 화면 오른쪽 위에서 **라이트 · 다크 · 시스템**을 선택합니다. 선택은 이 브라우저에 저장되며, 새로고침 후에도 유지됩니다. 시스템 모드는 운영체제의 밝기 설정을 따릅니다. 테마 전환은 입력 중인 판정이나 선택한 실행을 다시 불러오지 않습니다.

Grafana는 상단 **테마 설정 → Interface theme → Save preferences**에서 바꿉니다. 오른쪽 위 프로필 메뉴의 **Change theme**에서도 바로 선택할 수 있습니다. Grafana의 선택은 로그인한 사용자 설정으로 저장됩니다. 검토 화면에서 Grafana 링크를 열면 현재 검토 화면의 밝기로 열립니다.

## 화면 언어와 다국어 판정

결과 검토 화면 오른쪽 위에서 **한국어 / English**를 선택합니다. 메뉴·버튼·입력 안내·날짜 표시가 함께 바뀌며, 작성 중인 판정·선택한 근거·검색 조건은 유지됩니다. 선택은 브라우저에 저장됩니다. [한국어 화면](http://127.0.0.1:8765/?lang=ko)과 [영문 화면](http://127.0.0.1:8765/?lang=en) 링크로 바로 열 수도 있습니다.

판정 이유와 평가자 이름은 여러 언어를 섞어 입력할 수 있습니다. 입력한 원문은 자동 번역하지 않으며, 아랍어·히브리어의 글 방향도 처리합니다. 판정 결과는 화면 언어와 관계없이 `pass / fail / inconclusive` 코드로 저장합니다. 평가자·기준 버전은 100자, 판정 이유는 5,000자까지이며 브라우저와 서버가 같은 **Unicode 코드 포인트** 기준으로 계산합니다. 결합 이모지와 조합 문자는 보이는 글자 하나가 여러 코드 포인트일 수 있습니다.

Grafana 상단의 **한국어 / English**로 대시보드를 전환합니다. 두 화면의 조회 쿼리와 데이터는 같습니다. 영문 화면은 `grafana/dashboard.json`과 `scripts/grafana.en.json`에서 생성하며, 한국어 구성을 수정한 뒤 아래 명령으로 함께 갱신합니다.

```bash
python3 scripts/build_grafana_languages.py
python3 scripts/build_grafana_languages.py --check
```

## 보관과 종료

- `.state/objects/`: 가져온 파일의 내용 기반 사본입니다. 원본 폴더는 변경하지 않습니다.
- `.state/postgres/`: 전용 개발 DB입니다. 기본 포트는 `55438`입니다.
- `.state/config.json`, `db.password`, `.state/grafana/`: 로컬 인증 정보입니다. Git과 공유 ZIP에서 제외합니다.
- `SIMASSET_STATE_DIR`로 별도 위치를 지정할 수 있습니다. 기존 팀 DB나 다른 프로젝트 DB를 이 도구에 연결하지 않습니다.

서버 터미널에서 `Ctrl+C`로 웹 서버를 종료합니다. 이후 다음 명령으로 이 시제품의 DB만 종료합니다.

```bash
uv run python scripts/local_db.py stop
```

## Grafana 조회 구성

판정 입력은 이 웹 화면에서 처리하고, Grafana에는 조회용 SQL 뷰만 허용합니다. Grafana OSS 13.3.1의 macOS ARM64 공식 배포본에서 요약 수치·상태 분포·상세 표의 실제 로딩과 조회 값을 확인했습니다. 다른 환경에서 처음 구성할 때는 [공식 설치 안내](https://grafana.com/docs/grafana/latest/setup-grafana/installation/mac/)에 따라 Grafana를 설치한 뒤 다음 명령을 실행합니다.

```bash
uv run python scripts/grafana_readonly.py
grafana server --homepath /absolute/path/to/grafana \
  --config "$PWD/.state/grafana/grafana.ini"
```

첫 실행용 로그인은 로컬 `.state/grafana/local-login.json`에 있습니다. 서버 주소는 `127.0.0.1:3015`입니다. 구성 스크립트는 DB 비밀번호를 회전하므로 실행 중인 Grafana가 있다면 유지 관리 시점에 실행합니다. 기존 Grafana 관리자 비밀번호를 초기화하는 도구는 아닙니다.

이 Mac의 설치본은 `.state/grafana/runtime/grafana-13.3.1/`에 있습니다. 이미 구성된 환경을 다시 켤 때는 DB를 먼저 시작하고 아래 서버 명령만 실행합니다. 구성 스크립트를 다시 실행할 필요는 없습니다.

```bash
uv run python scripts/local_db.py start
.state/grafana/runtime/grafana-13.3.1/bin/grafana server \
  --homepath "$PWD/.state/grafana/runtime/grafana-13.3.1" \
  --config "$PWD/.state/grafana/grafana.ini"
```

[Grafana 결과 검토](http://127.0.0.1:3015/d/simasset-local-review)는 전체 수집분을 표시합니다. 기간 선택기는 숨겼고 30초 자동 갱신을 사용합니다. 측정값은 최대 1,000행을 조회하며, 에셋·측정 항목·유효 여부로 표를 필터링할 수 있습니다. 표의 숫자와 단위는 SI 기준이며 원본 항목명은 유지합니다. 측정값 표는 기본적으로 접혀 있으며 필요할 때 펼칩니다. 실행 보기 링크로 해당 실행의 영상·판정 화면에 바로 이동합니다. 전체 실행 ID와 에셋 해시는 검토 화면의 검사 조건·파일 탭에서도 확인할 수 있습니다.

Grafana의 DB 계정은 뷰 SELECT만 허용하며 테이블 INSERT/UPDATE 권한이 없습니다. 공식 배포본의 SHA-256을 검증했고, 추가 플러그인 자동 설치는 껐습니다. [공식 PostgreSQL 데이터소스 안내](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/)도 별도 읽기 전용 계정을 권장합니다.

## 검증과 다음 연결

```bash
uv run pytest -q
node --test tests/*.test.mjs
python3 scripts/build_grafana_languages.py --check
```

테스트는 `simasset_review_test_...` 임시 DB를 만들고 끝난 뒤 해당 DB만 정리합니다. 실제 시제품 데이터는 지우지 않습니다.

- [필드 대응·선택 이유·남은 질문](docs/필드대응과선택.md)
- [로컬 검증 결과](docs/검증결과.md)
- [화면 개편과 검증](docs/화면개편_검증.md)
- [CPU·GPU 비교 실행 안내](docs/환경비교_실행안내.md)
- [Nebius L40S 실측 결과](docs/Nebius_GPU_검증.md)
- [팀 공유 메시지 초안](docs/팀공유_초안.md)
- [결과 제출·ID·수정 규칙 초안](docs/결과제출_계약초안.md)
- [팀원 재현 점검과 짧은 시연](docs/팀원_재현점검.md)

공유된 원본 하네스·에셋과 개별 실행 원문은 이 저장소에 포함하지 않습니다. 검증 수치와 비교 그림은 문서에 포함하며, 제공받은 원본을 따로 지정해 재현합니다.
