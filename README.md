# kiro-local-router

A PoC for **routing work in Kiro by task type**, without hacking or patching Kiro itself:

| Task type | Agent | Which model |
|---|---|---|
| Documentation (README, ADR, runbook, changelog), doc translation, doc review | `docs-writer` | **Local LLM** (Ollama) via an MCP server |
| Design / Implement / Debug / IaC | `implementer` | **Regular Kiro model** (AWS) |
| Commit message / PR description | `implementer` | Calls the local LLM for this one tool only, then Kiro double-checks |

Principle: it uses only **custom agents (JSON)** and an **MCP server**, both official Kiro interfaces. So there is nothing to chase after Kiro updates, and it works with the license your office already bought.

```
Kiro CLI / IDE  ──(agent: docs-writer)──▶  Kiro model (AWS)   ← sees only "path + instruction" and a short result
                                              │ calls MCP tool
                                              ▼
                                   kiro-localllm (MCP server, runs locally)
                                   reads files itself → sends to Ollama → writes the output file itself
                                              ▼
                                   Ollama (local) / OpenRouter / custom endpoint
```

**Why it saves cost:** the tools take only a *path* and write results to disk themselves, so file contents never pass through the Kiro model. Kiro gets back just a short line such as `OK: wrote 1240 words to docs/api.md`.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Install Ollama + pull a model](#2-install-ollama--pull-a-model)
3. [Install this project (MCP server + agents)](#3-install-this-project-mcp-server--agents)
4. [Test before using with Kiro](#4-test-before-using-with-kiro)
5. [Using with Kiro CLI](#5-using-with-kiro-cli)
6. [Using with Kiro IDE](#6-using-with-kiro-ide)
7. [The 4 tools](#7-the-4-tools)
8. [Configuration (.env)](#8-configuration-env)
9. [Switching providers: OpenRouter / custom](#9-switching-providers-openrouter--custom)
10. [Security](#10-security)
11. [Customization and extension](#11-customization-and-extension)
12. [Troubleshooting](#12-troubleshooting)
13. [Uninstall](#13-uninstall)

---

## 1. Prerequisites

- **Kiro CLI** (`kiro-cli`) installed and logged in (see the latest install instructions at <https://kiro.dev/docs/cli/>)
- **Python 3.10+** and `git`
- **Ollama** (next section)
- OS: Linux / macOS can use `install.sh` directly; for Windows see section 3.3

---

## 2. Install Ollama + pull a model

### 2.1 Install Ollama

| OS | How |
|---|---|
| Linux | `curl -fsSL https://ollama.com/install.sh | sh` |
| macOS | `brew install ollama` or download the app from <https://ollama.com/download> |
| Windows | Download the installer from <https://ollama.com/download> |

Start the service (on Linux/macOS, the install script usually starts it automatically):

```bash
ollama serve            # if not already running; leave it open in another terminal
curl http://localhost:11434/api/tags     # should return JSON
```

### 2.2 Pull a model

If you don't know your machine's capacity yet, start with the smallest model to try the PoC (the project default is `qwen3:4b`):

```bash
ollama pull llama3.2:3b
ollama run llama3.2:3b "Hello, answer briefly"

ollama pull qwen3:4b
ollama run qwen3:4b "Hello, answer briefly"     # check that it responds (type /bye to exit)

ollama list
ollama stop qwen3:4b
ollama rm qwen3:4b
```

Rough options by RAM/VRAM (numbers are rules of thumb; try them for real):

| Free memory | Models to try | Notes |
|---|---|---|
| ~3-8 GB | `qwen3:4b`, `llama3.2:3b` | Enough for summaries / short READMEs |
| ~9-16 GB | `qwen3:8b` | Noticeably better documentation quality |
| 32 GB or more | `qwen3:14b` or larger | Good for long docs / Thai translation |

Change the model via `OLLAMA_MODEL` in the `.env` file (no need to edit the agents).

### 2.3 Context window (important)

Ollama uses a short context by default. If you send a file that's too long, it gets silently truncated and the document comes out wrong. This project sets `num_ctx` on every request via `OLLAMA_NUM_CTX` (default 8192) and limits input size with `MAX_INPUT_CHARS` (default 20000 characters). These two values must be adjusted together:

```
MAX_INPUT_CHARS ≈ 3 × (OLLAMA_NUM_CTX − 2000)
```

For example, if you set `OLLAMA_NUM_CTX=16384`, set `MAX_INPUT_CHARS=40000` (a larger context uses more RAM). Thai text uses more tokens than English, so leave generous headroom.

---

## 3. Install this project (MCP server + agents)

### 3.1 Linux / macOS

```bash
git clone https://github.com/Saksuriyas/kiro-local-router.git
cd kiro-local-router

chmod +x install.sh
./install.sh
```

The script will:
1. Create `.venv` and install `kiro-localllm` (the MCP server) with its dependencies (`mcp<2`, `httpx`)
2. Create `.env` from `.env.example`
3. Create 2 agent files in `~/.kiro/agents/`, filling in the MCP server path for you

Options:

```bash
./install.sh --workspace /path/to/your/project   # install agents to <project>/.kiro/agents (commit to git to share with the team)
./install.sh --no-agents                          # install only the MCP server
PYTHON=python3.12 ./install.sh                    # choose your own Python
```

> The generated agents **embed the path to `.venv`**. If you move the project folder, run `./install.sh` again.

### 3.2 Edit `.env`

```bash
$EDITOR .env      # at minimum, make sure OLLAMA_MODEL matches the model you pulled
```

### 3.3 Windows (manual, untested)

We recommend **WSL2**, then follow section 3.1. For native Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy .env.example .env
```

Then copy `agents\*.json.template` to `%USERPROFILE%\.kiro\agents\`, remove the `.template` extension, and replace `__KIRO_LOCALLM_BIN__` with the full path to `.venv\Scripts\kiro-localllm.exe` (use `\\` in JSON).

---

## 4. Test before using with Kiro

First, test the wiring without any model (uses a built-in fake Ollama):

```bash
.venv/bin/python scripts/smoke_test.py --mock
```

You should see `PASS` on every line (including "MCP server lists 4 tools", which is tested over the real MCP protocol). Then test against real Ollama:

```bash
.venv/bin/python scripts/smoke_test.py
```

The script creates a temporary workspace (a small git repo), calls every tool with the configured model, and prints the workspace path so you can open the results in `docs/`. If the model is slow or the output is poor, try a larger model before concluding that the PoC doesn't work.

---

## 5. Using with Kiro CLI

```bash
cd /path/to/your/project

# Documentation work → local LLM
kiro-cli chat --agent docs-writer

# Design / implementation work → regular Kiro model
kiro-cli chat --agent implementer
```

If the flag differs in your installed version, see `kiro-cli chat --help` or use the `/agent` command in the chat to switch agents.

### Try it out (using `examples/sample_project`)

```bash
cd examples/sample_project
kiro-cli chat --v3 --agent docs-writer
```

```
> Write a new README for app.py to docs/README.generated.md in Thai, suitable for new developers
> Review docs/README.generated.md using app.py as the reference
> Translate docs/README.generated.md into English at docs/README.en.md
```

And on the implementer side:

```
kiro-cli chat --v3 --agent implementer

> 
> Add a /version endpoint to app.py that returns the value of env APP_VERSION
> Create a commit message for the staged changes
```

### What you should see

- When you give an instruction, Kiro asks permission for / calls tools named `generate_doc`, `review_docs`, etc. from `localllm`
- The output file appears on disk, while the chat shows only a short status line
- The MCP server's logs go to stderr; to inspect the tools independently of Kiro, run `.venv/bin/python scripts/smoke_test.py`

---

## 6. Using with Kiro IDE

The same MCP server works with Kiro IDE. Add it to `.kiro/settings/mcp.json` (per project) or `~/.kiro/settings/mcp.json` (machine-wide):

```json
{
  "mcpServers": {
    "localllm": {
      "command": "/ABSOLUTE/PATH/TO/kiro-local-router/.venv/bin/kiro-localllm",
      "args": [],
      "env": { "WORKSPACE_ROOT": "/ABSOLUTE/PATH/TO/your/project" },
      "autoApprove": ["summarize_diff"]
    }
  }
}
```

In the IDE you have to tell the chat to use the tools yourself (e.g. "use generate_doc from localllm to write ...") or write a steering file (`.kiro/steering/*.md`) saying that documentation tasks should call these tools. The agent JSON format in the IDE may differ from the CLI depending on version, so check the Kiro IDE docs first.

---

## 7. The 4 tools

Every tool returns a short text message; on failure it starts with `ERROR:` plus how to fix it. Every tool accepts optional `profile` and `model` parameters to override the provider/model per call.

| Tool | Main parameters | What it does | Returns |
|---|---|---|---|
| `generate_doc` | `sources[]`, `output`, `instruction`, `overwrite=false` | Reads the files in `sources` and writes a Markdown document to `output` | `OK: wrote N words to <path>` |
| `summarize_diff` | `kind` = `commit`\|`pr`\|`summary`, `staged`, `base`, `paths[]`, `output` | Summarizes `git diff` as a commit message (Conventional Commits) / PR description / summary bullets | The generated text itself (short) |
| `review_docs` | `path`, `criteria`, `reference_sources[]`, `output` | Reviews a document (accuracy/completeness/clarity/structure), optionally against reference files, and saves a report | `VERDICT: PASS\|NEEDS_WORK \| report: <path>` |
| `translate_doc` | `source`, `output`, `target_language`, `keep_terms[]`, `overwrite=false` | Translates Markdown (keeps structure, does not translate code blocks); auto-chunks long files | `OK: translated N chunk(s) ...` |

Notes on `summarize_diff`: by default it looks at the working tree; `staged=true` looks at the index; `base="main"` looks at `main...HEAD`.

---

## 8. Configuration (.env)

Read from `.env` at the project root (or the file pointed to by `KIRO_LOCALLM_ENV`). **Real environment variables take precedence** (you can set them via `env` in the agent JSON). Every variable is explained in `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `DEFAULT_PROFILE` | `local` | Provider the tools use if none is specified: `local` / `openrouter` / `custom` |
| `WORKSPACE_ROOT` | (the cwd Kiro runs in) | Boundary the tools may read/write within |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama address (can point to a shared GPU machine) |
| `OLLAMA_MODEL` | `qwen3:4b` | Model to use |
| `OLLAMA_NUM_CTX` | `8192` | Context window (tokens) |
| `OLLAMA_THINK` | (empty) | Set to `false` to disable thinking mode on models that support it (requires a recent Ollama) |
| `MAX_INPUT_CHARS` | `20000` | Maximum total characters per request |
| `MAX_FILE_BYTES` | `1000000` | Maximum file size it will read |
| `TRANSLATE_CHUNK_CHARS` | `6000` | Chunk size for `translate_doc` |
| `LLM_TIMEOUT` | `900` | Seconds |

> If the MCP server doesn't see the right workspace (error "outside the workspace root"), set `WORKSPACE_ROOT` to the project path in the agent's / mcp.json's `env`.

---

## 9. Switching providers: OpenRouter / custom

**OpenRouter**: in `.env`:

```
DEFAULT_PROFILE=openrouter        # or pass profile="openrouter" per call
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=<model id from openrouter.ai/models>
ALLOW_EXTERNAL_PROVIDERS=true     # must be enabled deliberately
```

**Custom (OpenAI-compatible)**, e.g. LM Studio, vLLM, or an internal company gateway:

```
CUSTOM_BASE_URL=http://gpu-box.internal:8000/v1
CUSTOM_MODEL=...
CUSTOM_API_KEY=...
CUSTOM_IS_INTERNAL=true           # on your own network → not blocked by the external guard
```

---

## 10. Security

- **External providers are disabled by default.** Data (code/docs) sent to OpenRouter leaves your machine and is different from the Kiro/AWS arrangement your office bought. Check your policy before setting `ALLOW_EXTERNAL_PROVIDERS=true`. Ollama on your own machine/network sends no data outside.
- **File scope restriction:** every path is resolved and must be inside `WORKSPACE_ROOT` (blocks `../` and symlink escapes).
- **No accidental overwrites:** `generate_doc`/`translate_doc` refuse if the output already exists, unless `overwrite=true`.
- **Protected files:** writing into `.git/` and files starting with `.env` is forbidden.
- The `docs-writer` agent **has no `write`/`shell` tools**, so it can write files only through the local LLM's tools.
- Output from a local model can be wrong. Read it over, and use `review_docs` with the source files as reference.

---

## 11. Customization and extension

- **Tune each tool's prompt:** `kiro_localllm/prompts.py`
- **Add a new tool:** add a function in `kiro_localllm/server.py` with `@mcp.tool()` + `@_guard` (following the existing tools), then run the smoke test
- **Tune agent behavior:** edit `prompt`, `tools`, `allowedTools` in `agents/*.json.template`, then run `./install.sh` again (or edit the files in `~/.kiro/agents/` directly)
- **Built-in tool names** in `tools`/`allowedTools` (`read`, `write`, `shell`, ...) may differ between Kiro versions; check the real names with `/tools` in the chat
- **Make Kiro's default agent route automatically:** add a steering file saying "documentation tasks should call the localllm tools", but the model may not follow it every time. A dedicated agent is more reliable.
- Ideas for next steps: a tool that pulls context from a repo's MCP (e.g. codekb) and hands it to the local model to write docs; a hook that runs diff summaries automatically

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cannot connect to http://localhost:11434` | Ollama isn't running → `ollama serve` |
| `model 'xxx' not found` | Not pulled yet → `ollama pull xxx` or fix `OLLAMA_MODEL` |
| `path ... is outside the workspace root` | Kiro started from a different folder → set `WORKSPACE_ROOT` |
| `inputs exceed MAX_INPUT_CHARS` | Send fewer files, or raise `MAX_INPUT_CHARS` + `OLLAMA_NUM_CTX` together |
| Content missing/garbled even though the file isn't long | Not enough context, or the model is too small. Try a larger model |
| Very slow responses | Model too large for RAM/VRAM (swapping) → use a smaller model; try `OLLAMA_THINK=false` |
| Kiro doesn't see the agent | Check that the file exists in `~/.kiro/agents/` (or `<project>/.kiro/agents/`) and the JSON is valid |
| Kiro doesn't see the `localllm` tool | Wrong `command` path in the agent (moved the folder?) → run `./install.sh` again; verify with `/tools` |
| `ERROR: output already exists` | Intentional → have Kiro call again with `overwrite=true`, or change the file name |
| `ModuleNotFoundError: mcp.server.fastmcp` | mcp 2.x was installed by accident → `.venv/bin/pip install "mcp>=1.2,<2"` |

To test the MCP server independently of Kiro: `.venv/bin/python scripts/smoke_test.py --mock`

---

## 13. Uninstall

```bash
rm ~/.kiro/agents/docs-writer.json ~/.kiro/agents/implementer.json   # or under <project>/.kiro/agents/
rm -rf kiro-local-router        # delete the whole project (including .venv)
ollama rm qwen3:4b              # remove the model if no longer needed (optional)
```

---

## Project structure

```
kiro-local-router/
├── README.md
├── install.sh                 # installs venv + agents
├── pyproject.toml
├── .env.example
├── agents/
│   ├── docs-writer.json.template   # documentation work → local LLM
│   └── implementer.json.template   # design/implement → Kiro model
├── kiro_localllm/
│   ├── server.py              # MCP server + 4 tools
│   ├── client.py              # Ollama / OpenAI-compatible providers
│   ├── fsutil.py              # path confinement
│   ├── prompts.py             # system prompts
│   └── config.py              # .env loader
├── scripts/
│   ├── smoke_test.py          # tests every tool + the MCP protocol
│   └── fake_ollama.py         # fake Ollama for wiring tests
└── examples/sample_project/   # sample project to try docs-writer on
```

## Remote machine authentication (CLI) | Device flow
```
kiro-cli login

Note: Use with Builder ID, Use with Google, Use with GitHub, or Use with Your Organization).

```

## API key authentication (CLI)
```
Linux/Mac:
export KIRO_API_KEY=ksk_xxxxxxxx
kiro-cli chat --no-interactive "your prompt here"

Windows:
$env:KIRO_API_KEY = "ksk_xxxxxxxx"
kiro-cli chat --no-interactive "your prompt here"

Note: Sign in to app.kiro.dev with your Kiro Pro, Pro+, Pro Max, or Power account.
```