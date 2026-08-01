"""把本專案同步進 AgentCore Runtime 的 codeLocation（加分項部署用）。

背景
----
`加分項_AgentCore_Runtime部署.md` §3.1 要求 AgentCore 骨架建在**獨立目錄**，不得
污染 `00-tech-stack.md` §3 的固定目錄結構。但 AgentCore Runtime 的 `codeLocation`
是 `app/<Name>/`，執行時 `from src...` 只在該目錄底下解析得到——「隔離」與「import
得到」這兩個要求互相拉扯。

解法是本腳本：repo 維持唯一真實來源，部署前把需要的檔案**複製**進 codeLocation。
`app/<Name>/src|data|prompts` 全部是產出物，**不得手動編輯**——下次執行會整個覆蓋。

路徑對應
--------
`src/loaders.py` 與 `src/reporting.py` 都以 `Path(__file__).resolve().parents[1]`
定位 `data/` 與 `prompts/`，也就是 `src/` 的上一層。因此三者必須平行擺放，
複製後不需要改任何路徑程式碼：

    app/UrbanSentinelOrch/
    ├── main.py          （entrypoint，手寫，不由本腳本管理）
    ├── src/             ← repo src/（排除 EXCLUDED_MODULES）
    ├── data/            ← repo data/
    └── prompts/         ← repo prompts/

用法
----
    python scripts/build_agentcore_package.py
    python scripts/build_agentcore_package.py --target <app/<Name> 的絕對路徑>
    python scripts/build_agentcore_package.py --check-only
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TARGET = (
    REPO_ROOT.parent / "urban-sentinel-agentcore" / "UrbanSentinelOrch"
    / "app" / "UrbanSentinelOrch"
)
"""預設 codeLocation。可用 --target 或環境變數 AGENTCORE_APP_DIR 覆寫。"""

EXCLUDED_MODULES = {
    # ws_manager 匯入 fastapi.WebSocket。AgentCore Runtime 不跑 FastAPI，
    # 帶進去只會讓部署包多裝一整套 web framework，而且 orchestrator 對推播是
    # 以 `ws_broadcaster=None` 參數注入，雲端本來就不需要它。
    "ws_manager.py",
}

SYNCED_DIRS = ("data", "prompts")

FORBIDDEN_IMPORTS = {"fastapi", "uvicorn", "starlette"}
"""複製後掃描用。這些套件不在 AgentCore 部署包的依賴裡，誤留 import 會在雲端
冷啟動時才炸——本地測不出來，所以打包階段就擋掉。"""

IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")


def _iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path


def _top_level_imports(path: Path) -> set[str]:
    """回傳檔案裡所有 import 的頂層套件名。解析失敗回空集合（不阻斷打包）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 是相對匯入，沒有頂層套件名
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def check_forbidden_imports(src_dir: Path) -> list[str]:
    """掃描複製後的 src/，回傳違規描述清單。"""
    problems: list[str] = []
    for path in _iter_python_files(src_dir):
        hits = _top_level_imports(path) & FORBIDDEN_IMPORTS
        if hits:
            rel = path.relative_to(src_dir.parent)
            problems.append(f"{rel} 匯入了 {', '.join(sorted(hits))}")
    return problems


def sync(target: Path) -> Path:
    """把 src/ + data/ + prompts/ 複製進 target。回傳複製後的 src 路徑。"""
    if not target.exists():
        raise SystemExit(
            f"找不到 codeLocation：{target}\n"
            "請先執行 agentcore create 產生骨架，或以 --target 指定正確路徑。"
        )

    src_dest = target / "src"
    if src_dest.exists():
        shutil.rmtree(src_dest)
    shutil.copytree(
        REPO_ROOT / "src",
        src_dest,
        ignore=IGNORE_PATTERNS,
    )

    removed: list[str] = []
    for name in EXCLUDED_MODULES:
        victim = src_dest / name
        if victim.exists():
            victim.unlink()
            removed.append(name)

    for dirname in SYNCED_DIRS:
        source = REPO_ROOT / dirname
        if not source.exists():
            continue
        dest = target / dirname
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, ignore=IGNORE_PATTERNS)

    print(f"[done] src/      → {src_dest}")
    if removed:
        print(f"       （已排除：{', '.join(sorted(removed))}）")
    for dirname in SYNCED_DIRS:
        if (REPO_ROOT / dirname).exists():
            print(f"[done] {dirname + '/':9s}→ {target / dirname}")

    return src_dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=os.environ.get("AGENTCORE_APP_DIR", str(DEFAULT_TARGET)),
        help="AgentCore codeLocation（app/<Name>/ 的路徑）",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只檢查 repo 的 src/ 有無禁用 import，不複製任何檔案",
    )
    args = parser.parse_args()

    if args.check_only:
        problems = check_forbidden_imports(REPO_ROOT / "src")
        problems = [p for p in problems if not p.startswith(f"src{os.sep}ws_manager.py")]
        if problems:
            print("[fail] 以下檔案含 AgentCore 部署包不支援的 import：", file=sys.stderr)
            for p in problems:
                print(f"       - {p}", file=sys.stderr)
            return 1
        print("[ok] repo src/ 無禁用 import（ws_manager.py 已排除在外）")
        return 0

    target = Path(args.target).resolve()
    src_dest = sync(target)

    problems = check_forbidden_imports(src_dest)
    if problems:
        print("[fail] 打包後仍有禁用 import，部署會在雲端冷啟動失敗：", file=sys.stderr)
        for p in problems:
            print(f"       - {p}", file=sys.stderr)
        return 1

    print("[ok] 相依檢查通過，可執行 agentcore dev / agentcore deploy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
