#!/usr/bin/env bash
set -euo pipefail

container_name="${1:?container name is required}"
health_url="${2:?health URL is required}"
timeout_seconds="${GITLAB_STARTUP_TIMEOUT:-1200}"
started_at="$(date +%s)"

while true; do
  status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "${container_name}" 2>/dev/null || true)"
  # バージョンやHostヘッダーによって/-/healthの公開可否が異なるため、
  # ログイン画面へリダイレクトできるトップURLを外部到達性の判定に使う。
  if curl --fail --silent --max-time 5 "${health_url}/" >/dev/null; then
    echo "ready: ${container_name} (${health_url})"
    exit 0
  fi
  now="$(date +%s)"
  if (( now - started_at >= timeout_seconds )); then
    echo "timeout: ${container_name} status=${status}" >&2
    docker logs --tail 100 "${container_name}" >&2 || true
    exit 1
  fi
  echo "waiting: ${container_name} status=${status}"
  sleep 15
done
