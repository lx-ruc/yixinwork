# 后端镜像：uv 锁定依赖 + Playwright Chromium（海报渲染）+ 启动时迁移
# 国内网络可经构建参数换源：--build-arg REGISTRY=docker.m.daocloud.io/
ARG REGISTRY=""
FROM ${REGISTRY}python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright

WORKDIR /app

# uv 经清华 PyPI 源安装（避免 ghcr 镜像拉取）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 海报 png 渲染依赖的 Chromium（构建期装好，运行期无网络要求）；
# 放在业务代码 COPY 之前——代码变更不触发浏览器重下
RUN uv run playwright install --with-deps chromium

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY skills ./skills
COPY scripts ./scripts

EXPOSE 8001
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# 建表 → 起服务（compose 内 postgres 就绪由 healthcheck + depends_on 保证）
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
