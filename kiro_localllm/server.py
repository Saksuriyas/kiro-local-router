"""kiro-localllm: MCP server exposing local-LLM-backed documentation tools to Kiro agents.

Design rule: tools take PATHS and write results to disk themselves, and return only a short
status line. File contents never travel through the (billed) Kiro model.
Never print to stdout here: stdout is the MCP stdio transport.
"""
from __future__ import annotations

import functools
import logging
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config

config.load_dotenv()

from . import fsutil, prompts  # noqa: E402
from .client import LLMError, chat  # noqa: E402
from .config import env_int  # noqa: E402
from .fsutil import ToolError  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[kiro-localllm] %(message)s")
log = logging.getLogger("kiro-localllm")

mcp = FastMCP("localllm")


def _words(text: str) -> int:
    return len(text.split())


def _collect(sources: list[str], extra_chars: int = 0) -> str:
    limit = env_int("MAX_INPUT_CHARS", 20000)
    parts, total = [], extra_chars
    for s in sources:
        text = fsutil.read_text(s)
        total += len(text)
        if total > limit:
            raise ToolError(
                f"inputs exceed MAX_INPUT_CHARS={limit} (got >{total}). "
                "Pass fewer/smaller files, or raise MAX_INPUT_CHARS and OLLAMA_NUM_CTX together."
            )
        parts.append(f"### FILE: {s}\n{text}")
    return "\n\n".join(parts)


def _guard(fn):
    """Turn expected failures into readable 'ERROR: ...' results instead of protocol errors."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ToolError, LLMError) as e:
            log.info("tool error: %s", e)
            return f"ERROR: {e}"
    return wrapper


# --------------------------------------------------------------------------- tools

@mcp.tool()
@_guard
def generate_doc(sources: list[str], output: str, instruction: str, overwrite: bool = False,
                 profile: str | None = None, model: str | None = None) -> str:
    """Write a documentation file with the local LLM (README, ADR, runbook, changelog, API notes).

    Reads the files in `sources`, follows `instruction`, and writes Markdown to `output`.
    Returns only a short status line. Not for code changes or architectural decisions.
    """
    body = _collect(sources, extra_chars=len(instruction))
    text = chat(prompts.WRITER, f"{instruction}\n\n{body}", profile, model)
    path = fsutil.write_text(output, text, overwrite)
    return f"OK: wrote {_words(text)} words to {path.relative_to(fsutil.root())}"


@mcp.tool()
@_guard
def summarize_diff(kind: str = "commit", staged: bool = False, base: str | None = None,
                   paths: list[str] | None = None, output: str | None = None,
                   overwrite: bool = False, profile: str | None = None,
                   model: str | None = None) -> str:
    """Summarize `git diff` with the local LLM.

    kind: 'commit' (Conventional Commit message), 'pr' (PR description) or 'summary'.
    Diff scope: working tree by default; staged=true for the index; base='main' for main...HEAD.
    paths: optional list of files to limit the diff. If `output` is given the text is also saved there.
    Returns the generated text (short) so it can be used directly.
    """
    if kind not in prompts.DIFF_KINDS:
        raise ToolError(f"kind must be one of: {', '.join(prompts.DIFF_KINDS)}")
    if staged and base:
        raise ToolError("use either staged=true or base=..., not both")
    cmd = ["git", "-C", str(fsutil.root()), "diff", "--no-color"]
    if staged:
        cmd.append("--cached")
    if base:
        if base.startswith("-"):
            raise ToolError("invalid base ref")
        cmd.append(f"{base}...HEAD")
    if paths:
        cmd += ["--", *[fsutil.check_inside(p) for p in paths]]

    def run(extra: list[str]) -> str:
        pos = cmd.index("--") if "--" in cmd else len(cmd)
        full = cmd[:pos] + extra + cmd[pos:]
        try:
            res = subprocess.run(full, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ToolError(f"git failed: {e}")
        if res.returncode != 0:
            raise ToolError(f"git diff failed: {res.stderr.strip()[:300]}")
        return res.stdout

    diff = run([])
    if not diff.strip():
        return "No changes found for the requested diff scope."
    stat = run(["--stat"])
    limit = env_int("MAX_INPUT_CHARS", 20000)
    note = ""
    if len(diff) > limit:
        diff, note = diff[:limit], f"(diff truncated to {limit} chars) "
    text = chat(prompts.DIFF_SYSTEM, f"{prompts.DIFF_KINDS[kind]}\n\nDIFF STAT:\n{stat}\nDIFF:\n{diff}",
                profile, model, temperature=0.3)
    if output:
        fsutil.write_text(output, text, overwrite)
    return f"{note}{text}".strip()


@mcp.tool()
@_guard
def review_docs(path: str, criteria: str = "", reference_sources: list[str] | None = None,
                output: str | None = None, overwrite: bool = True,
                profile: str | None = None, model: str | None = None) -> str:
    """Review a documentation file with the local LLM and save a findings report.

    Optionally pass `reference_sources` (code/config files) to check the doc's claims against.
    The report goes to `output` (default '<path stem>.review.md'). Returns the VERDICT line and report path.
    """
    refs = _collect(reference_sources or [], extra_chars=0) if reference_sources else ""
    doc = fsutil.read_text(path)
    limit = env_int("MAX_INPUT_CHARS", 20000)
    if len(doc) + len(refs) + len(criteria) > limit:
        raise ToolError(f"document + references exceed MAX_INPUT_CHARS={limit}")
    user = f"EXTRA CRITERIA: {criteria or 'none'}\n\nDOCUMENT ({path}):\n{doc}"
    if refs:
        user += f"\n\nREFERENCE FILES:\n{refs}"
    text = chat(prompts.REVIEWER, user, profile, model, temperature=0.1)
    verdict = text.splitlines()[0].strip() if text else ""
    if verdict not in ("VERDICT: PASS", "VERDICT: NEEDS_WORK"):
        verdict = "VERDICT: UNKNOWN"
    p = Path(path)
    target = output or str(p.with_name(f"{p.stem}.review.md"))
    saved = fsutil.write_text(target, text, overwrite)
    return f"{verdict} | report: {saved.relative_to(fsutil.root())}"


def split_markdown(text: str, limit: int) -> list[str]:
    """Split on blank lines (never inside ``` fences) into chunks of about `limit` chars."""
    blocks, cur, in_fence = [], [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        cur.append(line)
        if not in_fence and line.strip() == "":
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    chunks, buf = [], ""
    for b in blocks:
        if buf and len(buf) + len(b) + 1 > limit:
            chunks.append(buf)
            buf = ""
        buf += b + "\n"
    if buf.strip():
        chunks.append(buf)
    return chunks


@mcp.tool()
@_guard
def translate_doc(source: str, output: str, target_language: str,
                  keep_terms: list[str] | None = None, overwrite: bool = False,
                  profile: str | None = None, model: str | None = None) -> str:
    """Translate a Markdown document with the local LLM (e.g. English <-> Thai).

    Keeps Markdown structure and never translates code blocks. Long files are translated in chunks.
    keep_terms: words that must stay untranslated. Returns a short status line.
    """
    text = fsutil.read_text(source)
    keep = f"- Never translate these terms: {', '.join(keep_terms)}.\n" if keep_terms else ""
    system = prompts.TRANSLATOR.format(target=target_language, keep=keep)
    chunks = split_markdown(text, env_int("TRANSLATE_CHUNK_CHARS", 6000))
    done = []
    for i, chunk in enumerate(chunks, 1):
        log.info("translating chunk %d/%d", i, len(chunks))
        done.append(chat(system, chunk, profile, model, temperature=0.1))
    result = "\n\n".join(done)
    path = fsutil.write_text(output, result, overwrite)
    return f"OK: translated {len(chunks)} chunk(s) to {target_language}, {_words(result)} words -> {path.relative_to(fsutil.root())}"


def main() -> None:
    log.info("starting (workspace root: %s)", fsutil.root())
    mcp.run()


if __name__ == "__main__":
    main()
