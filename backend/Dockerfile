# 后端镜像：uv 锁定依赖 + Playwright Chromium（海报渲染）+ 启动时迁移
# 国内网络可经构建参数换源：--build-arg REGISTRY=docker.m.daocloud.io/
ARG REGISTRY=""
FROM ${REGISTRY}python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# uv 经清华 PyPI 源安装（避免 ghcr 镜像拉取）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv

# Chromium 系统依赖（运行库 + 中文字体）单独成层且置于 Python 依赖之前：
# 加/改依赖只重建后面的层，不再触发数百 MB apt 全量重装
RUN uvx playwright install-deps chromium

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 浏览器本体（npmmirror 镜像）；系统依赖已就位，无需 --with-deps。
# 海报 png 渲染依赖的 Chromium 构建期装好，运行期无网络要求
RUN uv run playwright install chromium

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
