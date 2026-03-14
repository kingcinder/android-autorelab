from pathlib import Path

from arelab.config import Settings
from arelab.tooling import detect_tools


def test_tool_detection_has_repo_wrappers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    settings = Settings.load(repo_root)
    tools = detect_tools(settings)
    assert tools["lpunpack"]
    assert tools["unpack_bootimg"]
    assert tools["avbtool"]
