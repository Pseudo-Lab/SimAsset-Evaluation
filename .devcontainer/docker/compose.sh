#!/usr/bin/env bash
# 프로젝트 루트의 .env를 사용해 docker compose를 실행합니다.
#   .devcontainer/docker/compose.sh up -d --build
#   .devcontainer/docker/compose.sh ps | logs -f app | down
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"

if [[ ! -f "$root/.env" ]]; then
  echo "$root/.env 가 없습니다. .env.sample 을 복사해 값을 채워주세요." >&2
  exit 1
fi
# VS Code 개발 컨테이너도 같은 값을 읽도록 compose 폴더에 연결합니다 (Git 제외).
ln -sfn ../../.env "$here/.env"

# 바인드 폴더를 호스트 사용자 소유로 먼저 만듭니다 (Docker가 root 소유로 만들지 않도록).
results="$(set -a; . "$root/.env"; echo "${SIMASSET_RESULTS_DIR:-}")"
mkdir -p "$root/review/.state/grafana/"{data,logs,plugins}
chmod 700 "$root/review/.state"
[[ -n "$results" ]] && mkdir -p "$results"

exec docker compose --project-directory "$here" -f "$here/compose.yml" "$@"
