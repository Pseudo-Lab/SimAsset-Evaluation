# MinIO 관리·전송용 도구 이미지.
# MinIO 공식 명령줄 도구(mc)는 오픈소스 배포가 끝나 공식 Python SDK를 씁니다.
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir --disable-pip-version-check minio==7.2.20
WORKDIR /workspace
