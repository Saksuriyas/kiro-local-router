# kiro-local-router

PoC สำหรับ **แบ่งงานใน Kiro ตามประเภท** โดยไม่ต้อง hack หรือ patch ตัว Kiro:

| ประเภทงาน | Agent | ใช้ model อะไร |
|---|---|---|
| เอกสาร (README, ADR, runbook, changelog), แปลเอกสาร, รีวิวเอกสาร | `docs-writer` | **Local LLM** (Ollama) ผ่าน MCP server |
| Design / Implement / Debug / IaC | `implementer` | **Kiro model ตามปกติ** (AWS) |
| Commit message / PR description | `implementer` | เรียก local LLM เฉพาะ tool นี้ แล้ว Kiro ตรวจซ้ำ |

หลักการ: ใช้แค่ **custom agent (JSON)** กับ **MCP server** ซึ่งเป็น interface ทางการของ Kiro ดังนั้น Kiro อัปเดตแล้วไม่ต้องตามแก้ และใช้ได้กับ license ที่ office ซื้อไว้

```
Kiro CLI / IDE  ──(agent: docs-writer)──▶  Kiro model (AWS)   ← เห็นแค่ "path + instruction" และผลลัพธ์สั้น ๆ
                                              │ เรียก MCP tool
                                              ▼
                                   kiro-localllm (MCP server, รันในเครื่อง)
                                   อ่านไฟล์เอง → ส่ง Ollama → เขียนไฟล์ผลลัพธ์เอง
                                              ▼
                                   Ollama (local) / OpenRouter / custom endpoint
```

**ทำไมถึงประหยัด:** tool รับแค่ *path* และเขียนผลลัพธ์ลงดิสก์เอง เนื้อไฟล์จึงไม่วิ่งผ่าน Kiro model เลย Kiro ได้รับกลับแค่บรรทัดสั้น ๆ เช่น `OK: wrote 1240 words to docs/api.md`

---

## สารบัญ

1. [สิ่งที่ต้องมี](#1-สิ่งที่ต้องมี)
2. [ติดตั้ง Ollama + โหลด model](#2-ติดตั้ง-ollama--โหลด-model)
3. [ติดตั้งโปรเจกต์นี้ (MCP server + agents)](#3-ติดตั้งโปรเจกต์นี้-mcp-server--agents)
4. [ทดสอบก่อนใช้กับ Kiro](#4-ทดสอบก่อนใช้กับ-kiro)
5. [ใช้งานกับ Kiro CLI](#5-ใช้งานกับ-kiro-cli)
6. [ใช้งานกับ Kiro IDE](#6-ใช้งานกับ-kiro-ide)
7. [Tools ทั้ง 4 ตัว](#7-tools-ทั้ง-4-ตัว)
8. [การตั้งค่า (.env)](#8-การตั้งค่า-env)
9. [สลับ provider: OpenRouter / custom](#9-สลับ-provider-openrouter--custom)
10. [ความปลอดภัย](#10-ความปลอดภัย)
11. [ปรับแต่งต่อยอด](#11-ปรับแต่งต่อยอด)
12. [แก้ปัญหา](#12-แก้ปัญหา)
13. [ถอนการติดตั้ง](#13-ถอนการติดตั้ง)

---

## 1. สิ่งที่ต้องมี

- **Kiro CLI** (`kiro-cli`) ติดตั้งและ login แล้ว (ดูวิธีติดตั้งล่าสุดที่ <https://kiro.dev/docs/cli/>)
- **Python 3.10+** และ `git`
- **Ollama** (หัวข้อถัดไป)
- OS: Linux / macOS ใช้ `install.sh` ได้เลย ส่วน Windows ดูหัวข้อ 3.3

---

## 2. ติดตั้ง Ollama + โหลด model

### 2.1 ติดตั้ง Ollama

| OS | วิธี |
|---|---|
| Linux | `curl -fsSL https://ollama.com/install.sh | sh` |
| macOS | `brew install ollama` หรือโหลดแอปจาก <https://ollama.com/download> |
| Windows | โหลดตัวติดตั้งจาก <https://ollama.com/download> |

เริ่ม service (Linux/macOS ที่ติดตั้งผ่านสคริปต์มักรันให้อัตโนมัติแล้ว):

```bash
ollama serve            # ถ้ายังไม่ได้รัน เปิดค้างไว้อีก terminal
curl http://localhost:11434/api/tags     # ต้องได้ JSON กลับมา
```

### 2.2 โหลด model

ยังไม่รู้ขนาดเครื่อง เริ่มจาก model เล็กสุดเพื่อลอง PoC ก่อน (ค่า default ในโปรเจกต์คือ `qwen3:4b`):

```bash
ollama pull llama3.2:3b
ollama run llama3.2:3b "สวัสดี ตอบสั้น ๆ" 

ollama pull qwen3:4b
ollama run qwen3:4b "สวัสดี ตอบสั้น ๆ"     # ทดสอบว่าตอบได้ (พิมพ์ /bye เพื่อออก)

ollama list
ollama stop qwen3:4b
ollama rm qwen3:4b
```

ตัวเลือกตาม RAM/VRAM โดยประมาณ (ตัวเลขเป็น rule of thumb ควรลองจริง):

| หน่วยความจำว่าง | model ที่น่าลอง | หมายเหตุ |
|---|---|---|
| ~3-8 GB | `qwen3:4b`, `llama3.2:3b` | พอสำหรับสรุป / README สั้น ๆ |
| ~9-16 GB | `qwen3:8b` | คุณภาพเอกสารดีขึ้นชัด |
| 32 GB ขึ้นไป | `qwen3:14b` หรือใหญ่กว่า | เหมาะกับเอกสารยาว / แปลไทย |

เปลี่ยน model ได้ที่ `OLLAMA_MODEL` ในไฟล์ `.env` (ไม่ต้องแก้ agent)

### 2.3 Context window (สำคัญ)

Ollama ใช้ context สั้นเป็นค่า default ถ้าส่งไฟล์ยาวเกินจะถูกตัดเงียบ ๆ ทำให้เอกสารเพี้ยน โปรเจกต์นี้ตั้ง `num_ctx` ให้ทุก request ผ่าน `OLLAMA_NUM_CTX` (default 8192) และจำกัดขนาด input ด้วย `MAX_INPUT_CHARS` (default 20000 ตัวอักษร) สองค่านี้ต้องปรับไปด้วยกัน:

```
MAX_INPUT_CHARS ≈ 3 × (OLLAMA_NUM_CTX − 2000)
```

เช่น ถ้าตั้ง `OLLAMA_NUM_CTX=16384` ก็ตั้ง `MAX_INPUT_CHARS=40000` (context ที่ใหญ่ขึ้นใช้ RAM เพิ่ม) เอกสารภาษาไทยใช้ token มากกว่าอังกฤษ ควรเผื่อให้มาก

---

## 3. ติดตั้งโปรเจกต์นี้ (MCP server + agents)

### 3.1 Linux / macOS

```bash
git clone https://github.com/Saksuriyas/kiro-local-router.git
cd kiro-local-router

chmod +x install.sh
./install.sh
```

สคริปต์จะ:
1. สร้าง `.venv` และติดตั้ง `kiro-localllm` (MCP server) พร้อม dependency (`mcp<2`, `httpx`)
2. สร้าง `.env` จาก `.env.example`
3. สร้างไฟล์ agent 2 ตัวใน `~/.kiro/agents/` โดยใส่ path ของ MCP server ให้เอง

ตัวเลือก:

```bash
./install.sh --workspace /path/to/your/project   # ติดตั้ง agent ไว้ที่ <project>/.kiro/agents (commit เข้า git แชร์ทีมได้)
./install.sh --no-agents                          # ติดตั้งเฉพาะ MCP server
PYTHON=python3.12 ./install.sh                    # เลือก Python เอง
```

> agent ที่สร้างจะ **ฝัง path ของ `.venv` ไว้** ถ้าย้ายโฟลเดอร์โปรเจกต์ ให้รัน `./install.sh` ใหม่

### 3.2 แก้ `.env`

```bash
$EDITOR .env      # อย่างน้อยเช็ค OLLAMA_MODEL ให้ตรงกับที่ pull ไว้
```

### 3.3 Windows (ทำเอง ยังไม่ได้ทดสอบ)

แนะนำใช้ **WSL2** แล้วทำตามหัวข้อ 3.1 หากต้องการ native Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy .env.example .env
```

จากนั้นคัดลอก `agents\*.json.template` ไปที่ `%USERPROFILE%\.kiro\agents\` ตัดนามสกุล `.template` ออก และแทน `__KIRO_LOCALLM_BIN__` ด้วย path เต็มของ `.venv\Scripts\kiro-localllm.exe` (ใช้ `\\` ใน JSON)

---

## 4. ทดสอบก่อนใช้กับ Kiro

ขั้นแรก ทดสอบ wiring โดยไม่ต้องมี model (ใช้ Ollama ปลอมในตัว):

```bash
.venv/bin/python scripts/smoke_test.py --mock
```

ต้องได้ `PASS` ทุกบรรทัด (รวม "MCP server lists 4 tools" ซึ่งทดสอบผ่าน MCP protocol จริง) แล้วทดสอบกับ Ollama จริง:

```bash
.venv/bin/python scripts/smoke_test.py
```

สคริปต์จะสร้าง workspace ชั่วคราว (git repo เล็ก ๆ) แล้วเรียกทุก tool ด้วย model ที่ตั้งไว้ และพิมพ์ path ของ workspace ให้ไปเปิดดูผลลัพธ์ใน `docs/` ได้ ถ้า model ตอบช้าหรือผลลัพธ์แย่ ให้ลอง model ที่ใหญ่ขึ้นก่อนสรุปว่า PoC ไม่เวิร์ก

---

## 5. ใช้งานกับ Kiro CLI

```bash
cd /path/to/your/project

# งานเอกสาร → local LLM
kiro-cli chat --agent docs-writer

# งาน design / implement → Kiro model ตามปกติ
kiro-cli chat --agent implementer
```

ถ้า flag ต่างจากนี้ในเวอร์ชันที่ติดตั้ง ดู `kiro-cli chat --help` หรือใช้คำสั่ง `/agent` ในหน้าแชทเพื่อสลับ agent

### ตัวอย่างที่ลองได้ (ใช้ `examples/sample_project`)

```bash
cd examples/sample_project
kiro-cli chat --v3 --agent docs-writer
```

```
> เขียน README ใหม่สำหรับ app.py ไปที่ docs/README.generated.md เป็นภาษาไทย เหมาะกับ developer ใหม่
> รีวิว docs/README.generated.md โดยใช้ app.py เป็นข้อมูลอ้างอิง
> แปล docs/README.generated.md เป็นภาษาอังกฤษไปที่ docs/README.en.md
```

และฝั่ง implementer:

```
kiro-cli chat --v3 --agent implementer

> เขียน README ภาษาไทยสำหรับ examples/sample_project/app.py ไปที่ docs/README.kiro.md ด้วยตัวคุณเอง
> เพิ่ม endpoint /version ใน app.py ที่คืนค่าจาก env APP_VERSION
> สร้าง commit message ให้ staged changes
```

### สิ่งที่ควรเห็น

- ตอนสั่ง Kiro จะขออนุญาต/เรียก tool ชื่อ `generate_doc`, `review_docs`, ฯลฯ จาก `localllm`
- ไฟล์ผลลัพธ์ปรากฏในดิสก์ ส่วนในแชทเห็นแค่บรรทัดสถานะสั้น ๆ
- log ของ MCP server ออกทาง stderr; ถ้าอยากดูเอง ให้รัน `.venv/bin/python scripts/smoke_test.py` เพื่อตรวจ tool แยกจาก Kiro

---

## 6. ใช้งานกับ Kiro IDE

MCP server ตัวเดียวกันใช้กับ Kiro IDE ได้ โดยเพิ่มใน `.kiro/settings/mcp.json` (ต่อโปรเจกต์) หรือ `~/.kiro/settings/mcp.json` (ทั้งเครื่อง):

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

ใน IDE ต้องสั่งใน chat ให้ใช้ tool เอง (เช่น "ใช้ generate_doc จาก localllm เขียน ... ") หรือเขียน steering file (`.kiro/steering/*.md`) ว่างานเอกสารให้เรียก tool เหล่านี้ รูปแบบ agent JSON ใน IDE อาจต่างจาก CLI ตามเวอร์ชัน ให้ตรวจเอกสารของ Kiro IDE ก่อน

---

## 7. Tools ทั้ง 4 ตัว

ทุก tool: คืนค่าเป็นข้อความสั้น ๆ ถ้าผิดพลาดจะขึ้นต้นด้วย `ERROR:` พร้อมวิธีแก้ ทุก tool รับ `profile` และ `model` (optional) เพื่อ override provider/model ต่อครั้งได้

| Tool | พารามิเตอร์หลัก | ทำอะไร | คืนค่า |
|---|---|---|---|
| `generate_doc` | `sources[]`, `output`, `instruction`, `overwrite=false` | อ่านไฟล์ใน `sources` เขียนเอกสาร Markdown ลง `output` | `OK: wrote N words to <path>` |
| `summarize_diff` | `kind` = `commit`\|`pr`\|`summary`, `staged`, `base`, `paths[]`, `output` | สรุป `git diff` เป็น commit message (Conventional Commits) / PR description / bullet สรุป | ตัวข้อความที่สร้าง (สั้น) |
| `review_docs` | `path`, `criteria`, `reference_sources[]`, `output` | รีวิวเอกสาร (accuracy/completeness/clarity/structure) เทียบกับไฟล์อ้างอิงได้ บันทึกรายงาน | `VERDICT: PASS\|NEEDS_WORK \| report: <path>` |
| `translate_doc` | `source`, `output`, `target_language`, `keep_terms[]`, `overwrite=false` | แปล Markdown (คงโครงสร้าง ไม่แปล code block) แบ่ง chunk อัตโนมัติสำหรับไฟล์ยาว | `OK: translated N chunk(s) ...` |

หมายเหตุ `summarize_diff`: ค่า default ดู working tree; `staged=true` ดู index; `base="main"` ดู `main...HEAD`

---

## 8. การตั้งค่า (.env)

อ่านจาก `.env` ที่ root โปรเจกต์ (หรือไฟล์ที่ชี้ด้วย `KIRO_LOCALLM_ENV`) โดย **environment variable จริงมีลำดับสูงกว่า** (ตั้งผ่าน `env` ใน agent JSON ได้) ทุกตัวมีคำอธิบายใน `.env.example`

| ตัวแปร | ค่า default | ความหมาย |
|---|---|---|
| `DEFAULT_PROFILE` | `local` | provider ที่ tool ใช้ถ้าไม่ระบุ: `local` / `openrouter` / `custom` |
| `WORKSPACE_ROOT` | (cwd ที่ Kiro รัน) | ขอบเขตที่ tool อ่าน/เขียนได้ |
| `OLLAMA_HOST` | `http://localhost:11434` | ที่อยู่ Ollama (ชี้ไปเครื่อง GPU กลางได้) |
| `OLLAMA_MODEL` | `qwen3:4b` | model ที่ใช้ |
| `OLLAMA_NUM_CTX` | `8192` | context window (token) |
| `OLLAMA_THINK` | (ว่าง) | ตั้ง `false` เพื่อปิดโหมดคิดของ model ที่รองรับ (ต้องใช้ Ollama ใหม่) |
| `MAX_INPUT_CHARS` | `20000` | ตัวอักษรรวมสูงสุดต่อ request |
| `MAX_FILE_BYTES` | `1000000` | ขนาดไฟล์สูงสุดที่ยอมอ่าน |
| `TRANSLATE_CHUNK_CHARS` | `6000` | ขนาด chunk ของ `translate_doc` |
| `LLM_TIMEOUT` | `900` | วินาที |

> ถ้า MCP server ไม่เห็น workspace ที่ถูกต้อง (error "outside the workspace root") ให้ตั้ง `WORKSPACE_ROOT` เป็น path โปรเจกต์ใน `env` ของ agent/mcp.json

---

## 9. สลับ provider: OpenRouter / custom

**OpenRouter** — ใน `.env`:

```
DEFAULT_PROFILE=openrouter        # หรือส่ง profile="openrouter" รายครั้ง
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=<model id จาก openrouter.ai/models>
ALLOW_EXTERNAL_PROVIDERS=true     # ต้องเปิดเองโดยตั้งใจ
```

**Custom (OpenAI-compatible)** เช่น LM Studio, vLLM, gateway ภายในบริษัท:

```
CUSTOM_BASE_URL=http://gpu-box.internal:8000/v1
CUSTOM_MODEL=...
CUSTOM_API_KEY=...
CUSTOM_IS_INTERNAL=true           # อยู่ในเครือข่ายตัวเอง → ไม่ติด guard external
```

---

## 10. ความปลอดภัย

- **External provider ถูกปิดเป็น default** ข้อมูล (โค้ด/เอกสาร) ที่ส่งไป OpenRouter ออกนอกเครื่องและต่างจาก Kiro/AWS ที่ office ซื้อไว้ ตรวจ policy ก่อนตั้ง `ALLOW_EXTERNAL_PROVIDERS=true` ส่วน Ollama ในเครื่อง/เครือข่ายตัวเองไม่มีข้อมูลออกนอก
- **จำกัดขอบเขตไฟล์:** ทุก path ถูก resolve และต้องอยู่ใน `WORKSPACE_ROOT` (กัน `../` และ symlink หนี)
- **ไม่เขียนทับโดยไม่ตั้งใจ:** `generate_doc`/`translate_doc` ปฏิเสธถ้า output มีอยู่แล้ว เว้นแต่ `overwrite=true`
- **ป้องกันไฟล์สำคัญ:** ห้ามเขียนใน `.git/` และไฟล์ที่ขึ้นต้น `.env`
- agent `docs-writer` **ไม่มี tool `write`/`shell`** จึงเขียนไฟล์ได้ผ่าน tool ของ local LLM เท่านั้น
- ผลลัพธ์จาก local model อาจผิดพลาดได้ ควรอ่านทวนและใช้ `review_docs` กับไฟล์ต้นทางเป็นอ้างอิง

---

## 11. ปรับแต่งต่อยอด

- **ปรับ prompt ของแต่ละ tool:** `kiro_localllm/prompts.py`
- **เพิ่ม tool ใหม่:** เพิ่มฟังก์ชันใน `kiro_localllm/server.py` ด้วย `@mcp.tool()` + `@_guard` (ตามแบบ tool เดิม) แล้วรัน smoke test
- **ปรับพฤติกรรม agent:** แก้ `prompt`, `tools`, `allowedTools` ใน `agents/*.json.template` แล้วรัน `./install.sh` ใหม่ (หรือแก้ไฟล์ใน `~/.kiro/agents/` ตรง ๆ)
- **ชื่อ built-in tool** ใน `tools`/`allowedTools` (`read`, `write`, `shell`, ...) อาจต่างกันตามเวอร์ชัน Kiro ตรวจชื่อจริงด้วย `/tools` ในหน้าแชท
- **ให้ default agent ของ Kiro route เองอัตโนมัติ:** ใส่ steering file ว่า "งานเอกสารให้เรียก localllm tools" แต่ model อาจไม่ทำตามทุกครั้ง การแยกเป็น agent เฉพาะแน่นอนกว่า
- ไอเดียต่อ: tool ดึงบริบทจาก MCP ของ repo (เช่น codekb) แล้วส่งให้ local model เขียนเอกสาร, hook ให้รันสรุป diff อัตโนมัติ

---

## 12. แก้ปัญหา

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `cannot connect to http://localhost:11434` | Ollama ไม่ได้รัน → `ollama serve` |
| `model 'xxx' not found` | ยังไม่ pull → `ollama pull xxx` หรือแก้ `OLLAMA_MODEL` |
| `path ... is outside the workspace root` | Kiro เริ่มจากโฟลเดอร์อื่น → ตั้ง `WORKSPACE_ROOT` |
| `inputs exceed MAX_INPUT_CHARS` | ส่งไฟล์น้อยลง หรือเพิ่ม `MAX_INPUT_CHARS` + `OLLAMA_NUM_CTX` พร้อมกัน |
| เอกสารตกหล่น/เพี้ยนทั้งที่ไฟล์ไม่ยาว | context ไม่พอ หรือ model เล็กเกินไป ลอง model ใหญ่ขึ้น |
| ตอบช้ามาก | model ใหญ่เกิน RAM/VRAM (สลับลง swap) → ใช้ model เล็กลง; ลอง `OLLAMA_THINK=false` |
| Kiro ไม่เห็น agent | เช็คว่ามีไฟล์ใน `~/.kiro/agents/` (หรือ `<project>/.kiro/agents/`) และ JSON ถูกต้อง |
| Kiro ไม่เห็น tool `localllm` | path ใน `command` ของ agent ผิด (ย้ายโฟลเดอร์แล้ว?) → รัน `./install.sh` ใหม่ ทดสอบด้วย `/tools` |
| `ERROR: output already exists` | ตั้งใจให้เป็นแบบนี้ → ให้ Kiro เรียกซ้ำพร้อม `overwrite=true` หรือเปลี่ยนชื่อไฟล์ |
| `ModuleNotFoundError: mcp.server.fastmcp` | ติดตั้ง mcp 2.x โดยไม่ได้ตั้งใจ → `.venv/bin/pip install "mcp>=1.2,<2"` |

ทดสอบ MCP server แยกจาก Kiro: `.venv/bin/python scripts/smoke_test.py --mock`

---

## 13. ถอนการติดตั้ง

```bash
rm ~/.kiro/agents/docs-writer.json ~/.kiro/agents/implementer.json   # หรือใน <project>/.kiro/agents/
rm -rf kiro-local-router        # ลบทั้งโปรเจกต์ (รวม .venv)
ollama rm qwen3:4b              # ลบ model ถ้าไม่ใช้แล้ว (ไม่บังคับ)
```

---

## โครงสร้างโปรเจกต์

```
kiro-local-router/
├── README.md
├── install.sh                 # ติดตั้ง venv + agents
├── pyproject.toml
├── .env.example
├── agents/
│   ├── docs-writer.json.template   # งานเอกสาร → local LLM
│   └── implementer.json.template   # design/implement → Kiro model
├── kiro_localllm/
│   ├── server.py              # MCP server + 4 tools
│   ├── client.py              # Ollama / OpenAI-compatible providers
│   ├── fsutil.py              # path confinement
│   ├── prompts.py             # system prompts
│   └── config.py              # .env loader
├── scripts/
│   ├── smoke_test.py          # ทดสอบทุก tool + MCP protocol
│   └── fake_ollama.py         # Ollama ปลอมสำหรับทดสอบ wiring
└── examples/sample_project/   # โปรเจกต์ตัวอย่างให้ลอง docs-writer
```
