"""附录 C：只打印运行位置和配置是否存在，不打印任何密钥或地址。"""

import json
import os
from pathlib import Path
import sys


def configuration_status() -> dict[str, bool]:
    """环境变量的值可能敏感，诊断结果只保留存在与否。"""
    names = ("AGENTBOOK_BASE_URL", "AGENTBOOK_MODEL", "AGENTBOOK_API_KEY")
    return {name: bool(os.environ.get(name, "").strip()) for name in names}


def main() -> None:
    """帮助确认 Python、项目目录和真实调用前的配置条件。"""
    result = {
        "Python版本": sys.version.split()[0],
        "解释器": sys.executable,
        "当前目录": str(Path.cwd()),
        "当前目录包含 examples": (Path.cwd() / "examples").is_dir(),
        "配置是否存在": configuration_status(),
        "联网": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    assert all(isinstance(value, bool) for value in configuration_status().values())
    main()
