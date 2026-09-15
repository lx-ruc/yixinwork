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

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
