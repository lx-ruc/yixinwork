#!/bin/sh
# 容器入口：先建表/迁移，再启动服务
set -e
echo "[entrypoint] alembic upgrade head ..."
uv run alembic upgrade head
echo "[entrypoint] starting: $*"
exec "$@"
