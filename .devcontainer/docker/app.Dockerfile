# syntax=docker/dockerfile:1.7
# 결과 검토 도구(review/) 실행·개발용 이미지.
# 의존 패키지는 /opt/venv 에만 설치하고, 소스는 실행 시 /workspace 로 연결합니다.
# 빌드 컨텍스트는 review/ 이며 pyproject.toml, uv.lock 만 사용합니다
# (app.Dockerfile.dockerignore 참고).

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv
FROM node:22-bookworm-slim AS node

FROM python:3.11-slim-bookworm

ARG HOST_UID=1000
ARG HOST_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/workspace/review/src \
    MUJOCO_GL=osmesa \
    PYOPENGL_PLATFORM=osmesa \
    LIBGL_ALWAYS_SOFTWARE=1

# PostgreSQL 16 클라이언트(psql), 영상 인코딩·검사용 ffmpeg/ffprobe, git,
# MuJoCo 화면 없는 영상 렌더링용 OSMesa(llvmpipe 소프트웨어 렌더러).
# docs/환경비교_실행안내.md의 Linux 준비 패키지와 같습니다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg git ffmpeg postgresql-common \
      libosmesa6 libegl1 libgl1 unzip \
 && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/
# 화면 모듈 테스트(node --test)용 Node.js
COPY --from=node /usr/local/bin/node /usr/local/bin/node

RUN groupadd -g ${HOST_GID} dev \
 && useradd -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/bash dev \
 && mkdir -p /opt/venv /opt/simasset /workspace /data/results \
 && chown -R ${HOST_UID}:${HOST_GID} /opt/venv /opt/simasset /workspace

USER dev
WORKDIR /opt/simasset
COPY --chown=dev:dev pyproject.toml uv.lock ./
# uv.lock 그대로 설치. 프로젝트 자체는 PYTHONPATH(/workspace/review/src)로 불러옵니다.
RUN uv sync --locked --no-install-project --extra test --extra benchmark \
 && rm -rf /tmp/uv-cache

# 저장소 README의 `simasset-review ...` 명령을 그대로 쓰기 위한 실행 파일
USER root
RUN printf '#!/bin/sh\nexec python -m simasset_review.cli "$@"\n' > /usr/local/bin/simasset-review \
 && chmod 755 /usr/local/bin/simasset-review
USER dev

WORKDIR /workspace/review
CMD ["simasset-review", "serve"]
