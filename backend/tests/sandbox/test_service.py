"""沙箱测试：加固项验证（docker 门控）+ 纯逻辑单测（文件名清洗/截断）。"""

import pytest

from app.sandbox.service import (
    SANDBOX_LABEL,
    SandboxService,
    safe_filename,
    truncate_stdout,
)


def _docker_available() -> bool:
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return False
    return (
        subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=10,
        ).returncode
        == 0
    )


requires_docker = pytest.mark.skipif(not _docker_available(), reason="docker 不可用")


def _service(**kw) -> SandboxService:
    base = dict(image="yixin-sandbox:latest", timeout_seconds=30)
    return SandboxService(**{**base, **kw})


def _labeled_containers() -> int:
    import subprocess

    out = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={SANDBOX_LABEL}"],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.split()
    return len(out)


# ---- 纯逻辑单测 ----


def test_safe_filename_strips_paths_and_unsafe_chars():
    assert safe_filename("out/result.csv") == "result.csv"
    assert safe_filename("..\\evil.png") == "evil.png"
    assert safe_filename("..") is None
    assert safe_filename("a;b.png") is None
    assert safe_filename("中文结果.xlsx") == "中文结果.xlsx"


def test_truncate_stdout():
    text = "x" * 9000
    out = truncate_stdout(text)
    assert out.startswith("x" * 8000)
    assert "截断" in out
    assert truncate_stdout("short") == "short"


# ---- docker 门控集成 ----


@requires_docker
async def test_sandbox_runs_code_and_collects_files():
    result = await _service().run_code(
        "import pandas as pd\n"
        "df = pd.DataFrame({'月份': ['7月', '8月'], '销量': [120, 150]})\n"
        "print('rows:', len(df))\n"
        "df.to_csv('out/销量.csv', index=False)"
    )
    assert result.ok
    assert result.exit_code == 0
    assert "rows: 2" in result.stdout
    assert "销量.csv" in result.files
    assert b",120" in result.files["销量.csv"] or "120".encode() in result.files["销量.csv"]


@requires_docker
async def test_sandbox_timeout_killed():
    result = await _service(timeout_seconds=5).run_code("import time\ntime.sleep(120)")
    assert result.timed_out
    assert result.exit_code is None
    assert result.files == {}


@requires_docker
async def test_sandbox_network_blocked():
    result = await _service().run_code(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('93.184.216.34', 80), timeout=3)\n"
        "    print('NETWORK-OK')\n"
        "except OSError as e:\n"
        "    print('NETWORK-BLOCKED', type(e).__name__)\n"
    )
    assert result.ok
    assert "NETWORK-BLOCKED" in result.stdout


@requires_docker
async def test_sandbox_non_root_user():
    result = await _service().run_code(
        "import os\nprint('uid:', os.getuid())"
    )
    assert result.ok
    assert "uid: 1000" in result.stdout


@requires_docker
async def test_sandbox_failure_returns_stderr_and_no_files():
    result = await _service().run_code(
        "print('before')\nopen('out/x.txt', 'w').write('x')\nraise SystemExit(3)"
    )
    assert not result.ok
    assert result.exit_code == 3
    assert result.files == {}  # 失败执行不回收产物


@requires_docker
async def test_sandbox_container_removed_after_run():
    before = _labeled_containers()
    await _service().run_code("print('hi')")
    await _service(timeout_seconds=5).run_code("import time; time.sleep(60)")
    assert _labeled_containers() == before  # 成功/超时执行后均无残留
