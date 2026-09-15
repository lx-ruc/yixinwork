"""代码沙箱：模型生成代码的 Docker 隔离执行（无网络/限额/非 root/用后销毁）。"""

from app.sandbox.service import SandboxResult, SandboxService

__all__ = ["SandboxResult", "SandboxService"]
