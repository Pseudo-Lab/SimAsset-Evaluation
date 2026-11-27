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
3. GitHub에서 기준 브랜치를 `main`으로 선택해 PR을 엽니다. [PR 양식](.github/pull_request_template.md)에 변경 이유, 바뀐 내용, 확인 방법과 결과를 적습니다. 의견을 먼저 받고 싶다면 Draft PR로 열면 됩니다.

`.env`, 로컬 DB·설정 파일, 팀에서 공유한 검사 원본과 영상은 PR에서 제외합니다. 결과를 재현하는 데 자료가 필요하면 공유 가능한 링크와 실행 조건을 남깁니다.
