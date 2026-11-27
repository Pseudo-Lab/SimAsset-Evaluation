# 저장소 사용 안내

## 어디서 시작하나요?

| 작업 | 먼저 볼 곳 |
| --- | --- |
| 검사 규약과 결과 형식 확인 | [검사환경 공통규약 v4](docs/검사환경-공통규약-전체본_v4.md) |
| 결과 파일 검증·가져오기, 검토 화면, 판정 | [review/README.md](review/README.md) |
| Docker 개발 환경, Grafana, MinIO | [컨테이너 안내](.devcontainer/README.md) |

## 로컬에서 실행하고 확인하기

Git, `uv`, Python 3.11, PostgreSQL 16 이상이 필요합니다. JavaScript 테스트를 실행할 때는 Node.js도 준비합니다. 아래 명령은 macOS 터미널이나 Windows의 WSL Ubuntu에서 실행합니다.

- **macOS**: Homebrew로 PostgreSQL 16을 설치했다면 시작 전에 `export PATH="$(brew --prefix postgresql@16)/bin:$PATH"`를 실행합니다.
- **Windows**: [Microsoft WSL 설치 안내](https://learn.microsoft.com/ko-kr/windows/wsl/install)에 따라 WSL Ubuntu를 열고, 아래 저장소 복제부터 종료까지 **Ubuntu 터미널에서** 진행합니다. 저장소는 `/mnt/c` 대신 Ubuntu 홈 아래에 두세요. PostgreSQL 16을 Ubuntu 패키지로 설치했다면 `export PATH="/usr/lib/postgresql/16/bin:$PATH"`를 실행합니다. 현재 `local_db.py`는 Unix 소켓을 사용하므로 이 경로로 개발을 시작할 수 있습니다. Windows 네이티브 실행 문제를 재현할 때는 사용한 셸, 저장소 경로 형태, PostgreSQL 버전을 함께 기록해 주세요.

```bash
cd ~
git clone https://github.com/Pseudo-Lab/SimAsset-Evaluation.git
cd SimAsset-Evaluation/review
uv sync --locked --python 3.11 --extra test --extra benchmark
uv run python scripts/local_db.py start
uv run python scripts/local_db.py status
uv run simasset-review init-db
uv run simasset-review serve
```

브라우저에서 [결과 검토 화면](http://127.0.0.1:8765)을 엽니다. 같은 저장소를 이미 복제했다면 그 안의 `review/`에서 실행하면 됩니다. 결과 파일을 가져오는 방법은 [결과 검토 도구 안내](review/README.md#실행)에 있습니다.

DB가 실행 중이면 다른 터미널의 `review/`에서 관련 검사를 실행합니다.

```bash
uv run pytest -q
node --test tests/*.test.mjs
uv run python scripts/build_grafana_languages.py --check
```

웹 서버 터미널에서 `Ctrl+C`를 누른 뒤 같은 `review/` 폴더에서 아래 명령으로 전용 로컬 DB를 종료합니다.

```bash
uv run python scripts/local_db.py stop
```

## 첫 PR 올리기

1. 저장소 루트에서 `main`을 최신으로 맞추고 작업 브랜치를 만듭니다. 예를 들어 문서는 `docs/review-guide`, 실행 문제 수정은 `fix/windows-local-db`와 같이 이름을 붙일 수 있습니다.

   ```bash
   git switch main
   git pull --ff-only origin main
   git switch -c docs/review-guide
   ```

2. 변경과 확인을 마쳤으면 `git status`와 `git diff`를 보고 필요한 파일만 스테이징합니다. 커밋한 뒤 `git push -u origin HEAD`로 작업 브랜치를 올립니다.
3. GitHub에서 기준 브랜치를 `main`으로 선택해 PR을 엽니다. 제목은 `[유형] 작업 설명`으로 적고, [PR 양식](.github/pull_request_template.md)에 배경과 작업 내용을 남깁니다. 구현 중이거나 먼저 방향에 대한 의견을 받고 싶다면 Draft PR로 열면 됩니다.

   - **기능 구현** `[Feat] 검사 결과 CSV 내려받기 추가`
   - **버그 수정** `[Fix] Windows 로컬 DB 종료 오류 수정`
   - **문서** `[Docs] 결과 가져오기 안내 추가`
   - 구조 개선, 테스트, 설정 작업 등은 `[Refactor]`, `[Test]`, `[Chore]`처럼 주된 작업을 드러내는 유형을 사용합니다.

4. `main`에 반영할 작업은 PR을 통해 병합해 이력을 남깁니다. 11월 24일 회의에서 정한 현재 운영 방식은 필수 승인 인원과 브랜치 보호 없이 PR을 사용하는 것입니다. 의견이 필요하면 관련 팀원에게 리뷰를 요청합니다.

관련 이슈나 논의가 이미 있으면 PR 본문에서 연결합니다.

`.env`, 로컬 DB·설정 파일, 팀에서 공유한 검사 원본과 영상은 PR에서 제외합니다. 결과를 재현하는 데 자료가 필요하면 공유 가능한 링크와 실행 조건을 남깁니다.

### 작업에 맞는 확인 예시

| 작업 | 적을 내용 |
| --- | --- |
| 기능 구현 | 직접 실행해 본 기능, 관련 테스트 또는 시연 |
| 버그 수정 | 문제가 나는 조건, 수정 후 같은 조건에서 확인한 동작 또는 회귀 테스트 |
| 리팩터링·설정 | 영향을 받는 기존 기능을 확인한 테스트, 빌드·시작·설정 점검 |
| 화면·문서 | 화면은 캡처나 시연, 문서는 미리보기·링크나 실제 따라 해 본 절차 |
| 실험·데이터 | 비교 기준, 재현에 필요한 조건, 측정 자료나 데이터 검증 |

작은 작업은 확인한 내용만 짧게 적고, 추가 확인이 필요한 환경이나 조건이 있으면 덧붙입니다.
