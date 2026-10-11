"""Smoke test for kiro-localllm. No Kiro needed.

    python scripts/smoke_test.py          # against your real Ollama / configured profile
    python scripts/smoke_test.py --mock   # against a built-in fake Ollama (checks wiring only)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ap = argparse.ArgumentParser()
ap.add_argument("--mock", action="store_true", help="use a fake Ollama instead of a real model")
ap.add_argument("--profile", default=None, help="local | openrouter | custom")
args = ap.parse_args()

if args.mock:
    import fake_ollama

    _, port = fake_ollama.start(0)
    os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{port}"
    os.environ["OLLAMA_MODEL"] = fake_ollama.MODEL
if args.profile:
    os.environ["DEFAULT_PROFILE"] = args.profile

work = Path(tempfile.mkdtemp(prefix="kiro-localllm-test-"))
os.environ["WORKSPACE_ROOT"] = str(work)

from kiro_localllm import client, server  # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"[{PASS if ok else FAIL}] {name}" + (f"\n         {detail[:300]}" if detail else ""))


def git(*a: str) -> None:
    subprocess.run(["git", "-C", str(work), *a], check=True, capture_output=True)


# ---- workspace
(work / "app.py").write_text((ROOT / "examples/sample_project/app.py").read_text())
(work / "README.md").write_text("# Sample\n\nA tiny service.\n\n```bash\npython app.py\n```\n\nIt serves /health.\n")
git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
git("add", ".")
git("commit", "-qm", "init")
(work / "app.py").write_text((work / "app.py").read_text() + "\n# change\n")

# ---- provider
try:
    check("provider reachable", True, client.ping(args.profile))
except client.LLMError as e:
    check("provider reachable", False, str(e))
    sys.exit(1)

# ---- tools called directly
r = server.generate_doc(["app.py", "README.md"], "docs/generated.md", "Write a short README.")
check("generate_doc", r.startswith("OK") and (work / "docs/generated.md").is_file(), r)
r = server.generate_doc(["app.py"], "docs/generated.md", "again")
check("generate_doc refuses overwrite by default", r.startswith("ERROR"), r)
r = server.generate_doc(["../../etc/passwd"], "docs/x.md", "x")
check("path outside workspace is blocked", r.startswith("ERROR") and "outside" in r, r)
r = server.generate_doc(["app.py"], ".git/evil.md", "x", overwrite=True)
check(".git is protected", r.startswith("ERROR"), r)
r = server.review_docs("docs/generated.md", reference_sources=["app.py"])
check("review_docs", r.startswith("VERDICT:") and (work / "docs/generated.review.md").is_file(), r)
r = server.translate_doc("README.md", "docs/README.th.md", "Thai", keep_terms=["Docker"])
check("translate_doc", r.startswith("OK") and (work / "docs/README.th.md").is_file(), r)
r = server.summarize_diff(kind="commit")
check("summarize_diff (working tree)", not r.startswith("ERROR") and "No changes" not in r, r)
r = server.summarize_diff(kind="bogus")
check("summarize_diff rejects bad kind", r.startswith("ERROR"), r)
chunks = server.split_markdown("a\n\n```\nx\n\ny\n```\n\nb\n\n" * 50, 120)
check("split_markdown keeps code fences intact", all(c.count("```") % 2 == 0 for c in chunks), f"{len(chunks)} chunks")

# ---- through the real MCP stdio protocol
async def over_mcp() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kiro_localllm"],
                                   env={**os.environ, "PYTHONPATH": str(ROOT)})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            check("MCP server lists 4 tools", names == ["generate_doc", "review_docs", "summarize_diff", "translate_doc"], str(names))
            res = await s.call_tool("generate_doc", {"sources": ["app.py"], "output": "docs/via_mcp.md",
                                                     "instruction": "Describe the app."})
            text = res.content[0].text
            check("generate_doc over MCP", "OK" in text and (work / "docs/via_mcp.md").is_file(), text)

asyncio.run(over_mcp())

print(f"\nWorkspace used: {work}")
if args.mock:
    print("(mock mode: this verified the wiring, not output quality)")
sys.exit(1 if failures else 0)
