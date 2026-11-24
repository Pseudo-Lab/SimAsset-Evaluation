# 결과 검토 도구 컨테이너 환경

`review/` 결과 검토 도구를 Docker 안에서 실행합니다. 호스트에는 Docker 외에 아무것도 설치하지 않습니다. 저장소의 코드와 스크립트는 수정하지 않고 그대로 호출합니다.

## 구성

| 서비스 | 내용 | 외부 포트 (`.env`) |
| --- | --- | --- |
| `db` | PostgreSQL 16. 컨테이너 안 `127.0.0.1:55438` | `DB_PORT` |
| `bootstrap` | `simasset-review init-db`, 처음 한 번 `scripts/grafana_readonly.py` 실행 후 종료 | 없음 |
| `app` | `simasset-review serve` (127.0.0.1:8765). VS Code 개발 컨테이너도 여기 붙습니다 | 없음 (proxy 경유) |
| `grafana` | Grafana OSS 13.3.1 (127.0.0.1:3015) | 없음 (proxy 경유) |
| `proxy` | nginx. 외부 포트를 받아 앱·Grafana로 전달 | `REVIEW_PORT`, `GRAFANA_PORT` |

앱 코드는 DB 주소가 `127.0.0.1`이어야 하고, 웹 서버도 `127.0.0.1`에만 연결하며, 접속 주소(Host)도 `127.0.0.1`·`localhost`만 받습니다. 그래서 모든 서비스가 `db` 컨테이너의 네트워크를 함께 쓰고(`network_mode: service:db`), 외부 포트는 `db` 서비스에서만 엽니다. `proxy`는 다음을 처리합니다.

- 검토 화면에 기본 인증(`REVIEW_AUTH_USER` / `REVIEW_AUTH_PASSWORD`)을 겁니다. 앱 자체에는 로그인이 없습니다.
- 앱으로 넘길 때 Host·Origin을 내부 주소로 바꿉니다. 그 전에 Origin이 접속 주소와 같은지 프록시가 먼저 확인하므로, 다른 사이트에서 보낸 저장 요청은 403으로 막힙니다.
- 화면과 대시보드에 고정된 `127.0.0.1:8765`, `127.0.0.1:3015` 링크를 `http://PUBLIC_HOST:포트`로 바꿔 보냅니다.

## 파일

```
.env                          # 실제 값 (Git 제외). 견본: .env.sample
.devcontainer/
  devcontainer.json           # VS Code: app 컨테이너에 연결
  docker/
    compose.sh                # .env를 연결해 docker compose 실행
    compose.yml
    app.Dockerfile            # Python 3.11 + uv.lock 의존성(/opt/venv) + psql 16 + ffmpeg + node
    app.Dockerfile.dockerignore
    bootstrap.sh
    nginx/review.conf.template
    nginx/40-review-auth.sh   # 기본 인증 파일 생성
    storage/                  # MinIO 공유 버킷 (compose와 별개)
      storage.sh              # 팀원: review/evidence 올리기·받기 (push / pull / list)
      sync.py
      setup-minio.sh          # 관리자, 처음 한 번: 버킷·버킷 전용 공용 계정 만들기
      setup_minio.py
      storage.Dockerfile      # MinIO 공식 Python SDK (mc는 오픈소스 배포 종료)
```

### MinIO 공유 버킷으로 결과 주고받기

`review/evidence` 폴더와 버킷이 같은 구조입니다. 예를 들어 버킷의 `runs/<이름>/...`는 로컬의 `review/evidence/runs/<이름>/...`입니다. 접속 정보는 `.env`의 `MINIO_*` 값을 씁니다.

```bash
.devcontainer/docker/storage/storage.sh list                 # 버킷 내용 요약
.devcontainer/docker/storage/storage.sh pull                 # 버킷에만 있거나 바뀐 파일 받기 (SHA-256 검증)
.devcontainer/docker/storage/storage.sh push                 # 로컬에만 있거나 바뀐 파일 올리기
.devcontainer/docker/storage/storage.sh pull --prefix runs/simasset-env-v4.2/   # 일부만
.devcontainer/docker/storage/storage.sh push --dry-run       # 옮길 파일 수만 확인
.devcontainer/docker/storage/storage.sh verify               # 서버에 저장된 내용과 로컬 파일 대조 (내려받지 않음)
```

- 파일마다 SHA-256을 버킷에 함께 저장합니다. 이미 같은 파일은 건너뜁니다.
- 받을 때는 내려받은 내용을 검증한 뒤에만 저장합니다.
- 올릴 때마다 버킷 루트의 `manifest.json`에 전체 파일 목록·크기·SHA-256을 다시 씁니다.
- ZIP 파일은 올리지 않습니다. 압축을 푼 폴더만 공유합니다.
- `push`·`pull`은 파일을 지우지 않습니다. 버킷에서 빼야 할 때는 정확한 경로를 지정해 `storage.sh remove <경로>...`를 실행합니다. 버킷은 버전 관리가 켜져 있어, 지우거나 덮어쓴 파일도 이전 버전으로 남습니다.
- 받은 결과를 DB에 넣는 일(`simasset-review import`)은 서버 컴퓨터에서 합니다.

MinIO 버킷과 공용 계정은 MinIO 관리자가 처음 한 번만 만듭니다. `.env`의 `MINIO_ACCESS_KEY`·`MINIO_SECRET_KEY`에 관리자 키를 잠시 넣고 `.devcontainer/docker/storage/setup-minio.sh`를 실행합니다. 스크립트가 하는 일은 다음과 같습니다.

1. 버킷을 만들고 버전 관리를 켭니다.
2. 그 버킷에서만 읽기·쓰기·삭제하고 버전 영구 삭제는 거부하는 정책과 계정을 만듭니다.
3. 새 키로 권한을 확인한 뒤 `.env`의 두 키를 새 계정 키로 바꿉니다.

팀원은 `.env.sample`의 MinIO 항목에 받은 값만 채웁니다.

데이터 위치:

- PostgreSQL 데이터: Docker 볼륨 `simasset-review_pgdata`
- 가져온 파일 사본·Grafana 설정과 데이터: `review/.state/` (기존 위치, Git 제외)
- 가져올 결과 폴더: `.env`의 `SIMASSET_RESULTS_DIR` → 컨테이너 안 `/data/results` (읽기 전용)

## 실행

```bash
.devcontainer/docker/compose.sh up -d --build   # 처음 또는 이미지 변경 시
.devcontainer/docker/compose.sh ps
.devcontainer/docker/compose.sh logs -f app
.devcontainer/docker/compose.sh down            # 중지 (데이터 유지)
```

접속 주소는 아래 변수로 정해집니다. 공유기에서 외부 포트를 이 컴퓨터의 `REVIEW_PORT`·`GRAFANA_PORT`·`DB_PORT`로 넘기면(포트 포워딩) 외부에서도 접속할 수 있습니다.

| 대상 | 외부 (`PUBLIC_HOST`) | 내부망 (이 컴퓨터 IP) |
| --- | --- | --- |
| 결과 검토 (기본 인증) | `http://PUBLIC_HOST:PUBLIC_REVIEW_PORT` | `http://<내부 IP>:REVIEW_PORT` |
| Grafana | `http://PUBLIC_HOST:PUBLIC_GRAFANA_PORT/d/simasset-local-review` | `http://<내부 IP>:GRAFANA_PORT` |
| PostgreSQL (`simasset_review`, `POSTGRES_USER`) | `PUBLIC_HOST:<DB 외부 포트>` | `<내부 IP>:DB_PORT` |

실제 주소와 외부 포트 번호는 공개 저장소·이슈·PR에 적지 말고 팀 안에서만 공유합니다.

`REVIEW_PORT`·`GRAFANA_PORT`·`DB_PORT`는 이 컴퓨터에서 여는 포트이고, `PUBLIC_REVIEW_PORT`·`PUBLIC_GRAFANA_PORT`는 브라우저가 쓰는 외부 포트입니다. 화면 사이 링크와 Grafana 주소는 `PUBLIC_HOST`와 `PUBLIC_*_PORT`로 만듭니다. 그래서 내부망에서 접속해도 링크는 외부 주소를 가리킵니다.

`PUBLIC_HOST`나 포트를 바꾸면 다시 적용합니다.

```bash
.devcontainer/docker/compose.sh up -d
```

## 결과 가져오기와 테스트

결과 폴더를 `SIMASSET_RESULTS_DIR` 아래에 두고 컨테이너 안 경로로 지정합니다. 저장소 README의 명령과 같습니다.

```bash
.devcontainer/docker/compose.sh exec app simasset-review audit /data/results/<batch> --expected /data/results/<expected.json>
.devcontainer/docker/compose.sh exec app simasset-review import /data/results/<batch> \
  --recursive --namespace shared-incline-20261117 --origin team_shared

.devcontainer/docker/compose.sh exec app pytest -q
.devcontainer/docker/compose.sh exec app sh -c 'node --test tests/*.test.mjs'
.devcontainer/docker/compose.sh exec app python scripts/build_grafana_languages.py --check
```

### 팀 공유 샘플 묶음 (가져오기 완료)

`SimAsset_결과검토_재현묶음_20261118_v3.zip`(홈 검사 샘플 6건, 영상 8개)을 `review/evidence/shared/`에 풀어 두었습니다. 묶음 `읽어주세요.md`의 namespace·origin 그대로 가져왔습니다. 같은 명령을 다시 실행하면 6건 모두 `duplicate`로 처리됩니다.

```bash
S=/data/results/shared/SimAsset_결과검토_재현묶음_20261118_v3/samples
.devcontainer/docker/compose.sh exec app simasset-review audit "$S/results" --expected "$S/expected.json"
.devcontainer/docker/compose.sh exec app simasset-review import "$S/results" --recursive \
  --namespace probe-share-20261118 --origin local_reproduction
```

### 공유 하네스로 결과 만들기 (영상 포함)

앱 이미지에는 OSMesa가 들어 있어 화면 없이 MuJoCo 영상을 만듭니다(`MUJOCO_GL=osmesa`, llvmpipe 소프트웨어 렌더링, CPU 물리). 팀에서 공유한 ZIP을 `review/evidence/harness/` 아래에 풀고 실행합니다. 출력은 쓰기 가능한 `/workspace/review/evidence/...`로 지정하고, 가져올 때는 같은 폴더를 `/data/results/...`로 읽습니다.

```bash
unzip probe_env.zip -d review/evidence/harness/
.devcontainer/docker/compose.sh exec app python scripts/probe_check.py \
  --source /workspace/review/evidence/harness/probe_env \
  --output /workspace/review/evidence/runs/probe-check-01 --video
.devcontainer/docker/compose.sh exec app simasset-review audit /data/results/runs/probe-check-01/results \
  --expected /data/results/runs/probe-check-01/expected.json
.devcontainer/docker/compose.sh exec app simasset-review import /data/results/runs/probe-check-01/results \
  --recursive --namespace probe-check-01 --origin local_reproduction
```

빗면 검사는 `review/docs/환경비교_실행안내.md`의 `scripts/benchmark.py source ... --video`를 같은 방식으로 실행합니다.

가져온 기록은 DB에서 수정·삭제할 수 없습니다(append-only). 기능 시험용 결과는 `--origin fixture`로 구분하세요. DB를 완전히 비우려면 `compose.sh down -v`로 볼륨을 지워야 하며, 그러면 모든 결과와 판정이 사라집니다.

## VS Code 개발 컨테이너

이 폴더를 VS Code로 열고 **Reopen in Container**를 선택합니다. `app` 컨테이너에 `/workspace`로 연결되고, Python 인터프리터는 `/opt/venv/bin/python`입니다. 컨테이너를 닫아도 서비스는 계속 실행됩니다.

## 계정·비밀번호 변경

| 대상 | 변경 방법 |
| --- | --- |
| 검토 화면 기본 인증 | `.env`의 `REVIEW_AUTH_*` 수정 → `compose.sh up -d --force-recreate proxy` |
| Grafana 관리자 | `.env`의 `GRAFANA_ADMIN_PASSWORD`는 Grafana 데이터가 처음 만들어질 때만 적용됩니다. 이미 만들어졌으면 아래 명령으로 바꾼 뒤 `.env`도 같게 맞춥니다. |
| PostgreSQL | `POSTGRES_PASSWORD`는 볼륨이 처음 만들어질 때만 적용됩니다. 아래 명령으로 바꾼 뒤 `.env`를 수정하고 `compose.sh up -d`로 앱을 다시 만듭니다. 비밀번호는 URL에 들어가므로 영문·숫자·`-`·`_`만 씁니다. |

```bash
# Grafana 관리자 비밀번호
.devcontainer/docker/compose.sh exec grafana sh -c \
  'grafana cli --homepath "$GF_PATHS_HOME" --config "$GF_PATHS_CONFIG" admin reset-admin-password <새 비밀번호>'

# PostgreSQL 비밀번호
.devcontainer/docker/compose.sh exec db psql -U simasset_dev -d simasset_review \
  -c "ALTER ROLE simasset_dev PASSWORD '<새 비밀번호>'"
```

`review/.state/grafana/local-login.json`은 `grafana_readonly.py`가 만든 값입니다. 이 환경에서는 `.env`의 Grafana 관리자 값이 우선하므로 그 파일의 비밀번호는 쓰이지 않습니다.

Grafana 읽기 전용 DB 계정(`simasset_grafana_reader`)을 다시 만들려면 다음을 실행합니다.

```bash
.devcontainer/docker/compose.sh run --rm -e GRAFANA_RECONFIGURE=1 bootstrap
.devcontainer/docker/compose.sh restart grafana
```

## 보안 주의

- `BIND_ADDRESS=0.0.0.0`이면 `REVIEW_PORT`·`GRAFANA_PORT`·`DB_PORT`가 외부에 열립니다. 기본값 `admin/admin`은 바로 바꾸세요.
- `DB_PORT`는 PostgreSQL 관리자 계정(`POSTGRES_USER`)으로 접속됩니다. 외부 접속이 필요 없으면 `compose.yml`의 `db.ports`에서 DB 포트 줄을 지우거나, `.env`의 `BIND_ADDRESS=127.0.0.1`로 모든 포트를 이 컴퓨터 안으로 제한할 수 있습니다.
- 통신은 HTTP 평문입니다. 외부에서 쓰려면 앞단에 HTTPS를 두는 것을 권장합니다.
