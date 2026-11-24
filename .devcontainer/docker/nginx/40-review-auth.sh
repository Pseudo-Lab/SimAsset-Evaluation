#!/bin/sh
# 결과 검토 화면 기본 인증 파일을 .env 값으로 만듭니다 (salted SHA-1, 컨테이너 안에만 저장).
set -eu
: "${REVIEW_AUTH_USER:?REVIEW_AUTH_USER가 필요합니다}"
: "${REVIEW_AUTH_PASSWORD:?REVIEW_AUTH_PASSWORD가 필요합니다}"

mkdir -p /etc/nginx/auth
salt=$(head -c 8 /dev/urandom | xxd -p)
digest=$({ printf '%s' "$REVIEW_AUTH_PASSWORD"; printf '%s' "$salt" | xxd -r -p; } | sha1sum | cut -d' ' -f1)
hash=$({ printf '%s' "$digest" | xxd -r -p; printf '%s' "$salt" | xxd -r -p; } | base64 | tr -d '\n')

umask 027
printf '%s:{SSHA}%s\n' "$REVIEW_AUTH_USER" "$hash" > /etc/nginx/auth/review.htpasswd
chown root:nginx /etc/nginx/auth/review.htpasswd
echo "40-review-auth.sh: 검토 화면 로그인 사용자 '$REVIEW_AUTH_USER' 설정"
