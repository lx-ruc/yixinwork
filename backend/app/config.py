"""应用配置：全部来自环境变量 / .env，禁止硬编码密钥。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "agent-platform"

    database_url: str = (
        "postgresql+psycopg://agent:agent@localhost:5433/agent_platform"
    )
    storage_root: str = "./data/artifacts"
    # 附件上传暂存目录（发送时合并进消息后即删）
    upload_root: str = "./data/uploads"

    # 运行时技能目录（<dir>/<skill-name>/SKILL.md；相对 CWD 解析）
    skills_dir: str = "skills"

    # 代码沙箱（模型生成代码的 Docker 隔离执行）
    sandbox_image: str = "yixin-sandbox:latest"
    sandbox_timeout_seconds: int = 60
    sandbox_memory: str = "512m"
    sandbox_cpus: float = 1.0
    sandbox_max_output_mb: int = 20

    # 产物签名下载（HMAC；生产必须经环境变量覆盖）
    download_signing_secret: str = "dev-insecure-download-secret"
    download_url_ttl_seconds: int = 600

    # GLM（OpenAI 兼容协议）
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4-plus"

    # CORS（逗号分隔）
    allowed_origins: str = "http://localhost:5173"

    # 身份上下文：鉴权由宿主系统负责，模块只接收可信注入的 X-User-Id。
    # 生产部署置 true：缺失身份头直接 401；开发态用默认用户。
    require_user_header: bool = False
    dev_default_user_id: str = "dev-local-user"

    # 内部运维接口（用量汇总查询）令牌；为空表示未启用（一律 403）
    internal_api_token: str = ""

    # API 限流（按用户，缺身份头回退 IP）；<=0 关闭（测试态）
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
