# SimAsset 결과 검토 시제품

검사 결과 폴더를 검증해 로컬 PostgreSQL에 가져오고, 영상·시계열·측정값을 보면서 사람 판정을 남깁니다. 같은 결과를 다시 가져오면 중복으로 기록하고, 같은 실행 ID의 내용이 다르면 기존 결과를 보존한 채 충돌을 표시합니다.

현재 어댑터는 팀에서 공유한 `incline_env.zip`의 빗면 검사 출력에 맞췄습니다. 팀의 최종 스키마나 판정 규약은 아닙니다. 다른 검사 출력은 해당 검사에 맞는 검증기를 추가해야 합니다.

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

# 여러 하위 폴더의 summary.csv를 찾아 각각 검증합니다.
uv run simasset-review import /absolute/path/to/result-batch \
  --recursive --namespace shared-incline-20261117 --origin team_shared
```

출력의 `imported`, `duplicate`, `conflict`, `invalid`를 확인합니다. 일부가 실패하면 정상 항목은 유지하고 CLI는 종료 코드 2를 반환합니다. 오류를 고친 파일은 다시 가져올 수 있으며, 이전 시도 기록은 남습니다. 내용이 달라진 동일 ID를 강제로 덮어쓰는 옵션은 없습니다.

화면에서 실행을 선택하고 영상·그래프·원본 단위를 확인한 뒤 평가자, 검토 항목, 기준 버전, 이유를 입력합니다. 판정을 수정하면 새 기록이 이전 기록을 참조합니다. `ok` 같은 자동 상태가 사람의 통과 판정으로 바뀌지는 않습니다.

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

판정 입력은 이 웹 화면에서 처리하고, Grafana에는 조회용 SQL 뷰만 허용합니다. Grafana OSS 13.3.1의 macOS ARM64 공식 배포본으로 네 패널의 실제 로딩과 조회 값을 확인했습니다. 다른 환경에서 처음 구성할 때는 [공식 설치 안내](https://grafana.com/docs/grafana/latest/setup-grafana/installation/mac/)에 따라 Grafana를 설치한 뒤 다음 명령을 실행합니다.

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

[Grafana 결과 검토](http://127.0.0.1:3015/d/simasset-local-review)는 전체 수집분을 표시합니다. 기간 선택기는 숨겼고 30초 자동 갱신을 사용합니다. 측정값은 최대 1,000행을 조회하며, 에셋·측정 항목·유효 여부로 표를 필터링할 수 있습니다. 표의 숫자와 단위는 SI 기준이며 원본 항목명은 유지합니다. 실행 ID와 에셋 해시는 가로 스크롤로 확인합니다.

Grafana의 DB 계정은 뷰 SELECT만 허용하며 테이블 INSERT/UPDATE 권한이 없습니다. 공식 배포본의 SHA-256을 검증했고, 추가 플러그인 자동 설치는 껐습니다. [공식 PostgreSQL 데이터소스 안내](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/)도 별도 읽기 전용 계정을 권장합니다.

## 검증과 다음 연결

```bash
uv run pytest -q
```

테스트는 `simasset_review_test_...` 임시 DB를 만들고 끝난 뒤 해당 DB만 정리합니다. 실제 시제품 데이터는 지우지 않습니다.

- [필드 대응·선택 이유·남은 질문](docs/필드대응과선택.md)
- [로컬 검증 결과](docs/검증결과.md)
- [CPU·GPU 비교 실행 안내](docs/환경비교_실행안내.md)
- [Nebius L40S 실측 결과](docs/Nebius_GPU_검증.md)
- [팀 공유 메시지 초안](docs/팀공유_초안.md)

공유된 원본 하네스·에셋과 개별 실행 원문은 이 저장소에 포함하지 않습니다. 검증 수치와 비교 그림은 문서에 포함하며, 제공받은 원본을 따로 지정해 재현합니다.
