"""沙箱执行服务：一次执行 = 一个容器，结束即销毁。

加固清单（对应规格 code-sandbox）：
- 无网络：network_mode="none"
- CPU/内存/pids 限额：nano_cpus / mem_limit / pids_limit
- 时长上限：超时 kill，回传 timed_out
- 非 root：user="1000:1000"（镜像内 sandbox 用户）
- 产出限额：out/ 目录总量截断，stdout 截断
- 只读 rootfs + tmpfs 工作区；cap_drop ALL + no-new-privileges

文件回传：docker cp 读不到 tmpfs 内容（moby 已知限制），改为容器内把
out/ 打 tar→base64，经 stdout 以随机标记分段回传（标记每次执行随机，
模型代码无法伪造产物区）。
"""

import asyncio
import base64
import binascii
import concurrent.futures
import io
import logging
import re
import tarfile
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SANDBOX_LABEL = "yixin.sandbox"  # 容器标记，用于识别与清理
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._\-一-鿿]+$")
MAX_STDOUT_CHARS = 8_000  # 回传给 Agent 的 stdout 上限
# 容器内包装命令：代码经 env 注入 → 落 main.py → 执行 → 回传 out/（tar+base64）
WRAPPER_COMMAND = (
    'mkdir -p out && printf "%s" "$YIXIN_CODE" > main.py'
    ' && python main.py; ec=$?;'
    ' if [ -d out ] && [ -n "$(ls -A out 2>/dev/null)" ]; then'
    ' echo "$YIXIN_MARKER"; (cd out && tar -cf - . 2>/dev/null | head -c 67108864 | base64);'
    " fi;"
    " exit $ec"
)


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    timed_out: bool
    files: dict[str, bytes] = field(default_factory=dict)  # 安全文件名 → 内容

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def safe_filename(name: str) -> str | None:
    """沙箱产出的文件名不可信：只取 basename 且限定字符集。"""
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base in {".", ".."} or not SAFE_FILENAME.match(base):
        return None
    return base


def truncate_stdout(text: str, limit: int = MAX_STDOUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（stdout 截断，共 {len(text)} 字符）"


def split_output(logs: str, marker: str) -> tuple[str, bytes | None]:
    """把容器日志拆为（stdout 文本, 产物 tar 字节 | None）。"""
    idx = logs.rfind(marker)
    if idx == -1:
        return logs, None
    stdout = logs[:idx].rstrip("\n")
    b64 = logs[idx + len(marker):].strip()
    try:
        return stdout, base64.b64decode(b64, validate=False) if b64 else None
    except (ValueError, binascii.Error):
        logger.warning("沙箱产物 base64 解码失败，忽略")
        return stdout, None


class SandboxService:
    """经 Docker 执行模型生成的 Python 代码，收集 stdout 与 out/ 目录产物。"""

    def __init__(
        self,
        *,
        image: str,
        timeout_seconds: int = 60,
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 128,
        max_output_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._image = image
        self._timeout = timeout_seconds
        self._memory = memory
        self._cpus = cpus
        self._pids_limit = pids_limit
        self._max_output = max_output_bytes

    async def run_code(self, code: str) -> SandboxResult:
        """执行一段 Python 代码；无论成败容器都用后销毁。"""
        return await asyncio.to_thread(self._run_code_sync, code)

    # ---- 同步实现（docker SDK 阻塞调用，整体放线程） ----

    def _run_code_sync(self, code: str) -> SandboxResult:
        import docker
        import docker.errors

        client = docker.from_env()
        name = f"yixin-sbx-{uuid.uuid4().hex[:12]}"
        marker = f"__YIXIN_OUT_{uuid.uuid4().hex[:8]}__"
        container = None
        try:
            container = client.containers.create(
                self._image,
                ["sh", "-c", WRAPPER_COMMAND],
                name=name,
                user="1000:1000",
                working_dir="/home/sandbox",
                environment={"YIXIN_CODE": code, "YIXIN_MARKER": marker},
                network_mode="none",  # 无网络
                mem_limit=self._memory,
                nano_cpus=int(self._cpus * 1_000_000_000),
                pids_limit=self._pids_limit,
                read_only=True,  # rootfs 只读
                tmpfs={"/tmp": "size=32m", "/home/sandbox": "uid=1000,gid=1000,size=128m"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                labels={SANDBOX_LABEL: "1"},
                detach=True,
            )
            container.start()

            timed_out = False
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    exit_info = pool.submit(container.wait).result(
                        timeout=self._timeout
                    )
                except concurrent.futures.TimeoutError:
                    container.kill()
                    timed_out = True
                    exit_info = {"StatusCode": None}

            logs = container.logs(stdout=True, stderr=True).decode(
                "utf-8", errors="replace"
            )
            exit_code = exit_info.get("StatusCode")
            stdout, payload = split_output(logs, marker)
            files = (
                self._parse_outputs(payload)
                if not timed_out and exit_code == 0 and payload
                else {}
            )
            return SandboxResult(
                exit_code=exit_code,
                stdout=truncate_stdout(stdout),
                timed_out=timed_out,
                files=files,
            )
        except docker.errors.ImageNotFound:
            raise RuntimeError(f"沙箱镜像不存在: {self._image}（先构建/拉取）") from None
        finally:
            if container is not None:
                try:
                    container.remove(force=True)  # 用后销毁，不留残留
                except Exception:  # noqa: BLE001 销毁尽力而为，不掩盖执行结果
                    logger.warning("沙箱容器销毁失败: %s", name)
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _parse_outputs(self, payload: bytes) -> dict[str, bytes]:
        """从回传 tar 中解析产物文件，逐文件与总量限额。"""
        files: dict[str, bytes] = {}
        total = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
                while True:
                    try:
                        member = tar.next()
                    except (tarfile.ReadError, EOFError):
                        break  # head 截断的尾部，收到的部分继续用
                    if member is None:
                        break
                    if not member.isfile():
                        continue
                    name = safe_filename(member.name.rsplit("/", 1)[-1])
                    if name is None or name == "main.py":
                        continue
                    if total + member.size > self._max_output:
                        logger.warning("沙箱产物超出限额，剩余文件丢弃: %s", name)
                        break
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    files[name] = extracted.read()
                    total += member.size
        except tarfile.ReadError:
            logger.warning("沙箱产物 tar 解析失败，忽略全部产物")
        return files
