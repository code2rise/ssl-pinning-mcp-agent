# SSL Pinning Hash Generator — MCP Agentic System

An **MCP (Model Context Protocol) server** that exposes an SSL certificate pinning tool to any MCP-compatible AI client. Ask Claude, Continue.dev, Gemini, or any other MCP-aware client to generate SHA-256 SPKI hashes for Android/iOS SSL pinning — and the AI will autonomously call the tool, compute the hash from a live server, and return it ready to paste into your app's security config.

---

## Table of Contents

1. [Purpose & Background](#1-purpose--background)
2. [What is MCP and Why It Matters](#2-what-is-mcp-and-why-it-matters)
3. [Architecture](#3-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [How the SSL Pinning Tool Works](#6-how-the-ssl-pinning-tool-works)
7. [Prerequisites](#7-prerequisites)
8. [Installation & Setup](#8-installation--setup)
9. [Running the MCP Server](#9-running-the-mcp-server)
10. [Client Integration](#10-client-integration)
    - [Claude Code (CLI)](#101-claude-code-cli)
    - [Claude Desktop](#102-claude-desktop)
    - [Continue.dev (VS Code / JetBrains)](#103-continuedev-vs-code--jetbrains)
    - [Gemini CLI / Google AI Studio](#104-gemini-cli--google-ai-studio)
    - [Generic MCP Client (Python)](#105-generic-mcp-client-python)
11. [Prompt Considerations](#11-prompt-considerations)
12. [End-to-End Flow Walkthrough](#12-end-to-end-flow-walkthrough)
13. [Evolution from Tool-Calling Agent to MCP](#13-evolution-from-tool-calling-agent-to-mcp)
14. [Known Limitations & Troubleshooting](#14-known-limitations--troubleshooting)
15. [Claude Code MCP Configuration: Priority Order & Actual Setup](#15-claude-code-mcp-configuration-priority-order--actual-setup)

---

## 1. Purpose & Background

### What the project does

This project wraps an SSL certificate pinning utility as a **discoverable, protocol-standard MCP tool**. Any MCP-compatible AI client can connect to this server and ask:

- *"Generate the SSL pin for https://api.example.com"*
- *"What is the SHA-256 SPKI hash of the certificate at /tmp/cert.pem?"*
- *"Give me the Android network_security_config.xml entry for https://github.com"*

The AI will call the tool autonomously, compute the hash, and format the output — without any manual scripting required.

### SSL Pinning primer

SSL certificate pinning is a mobile security technique where an app is hardcoded to accept only a specific server certificate (or public key). If an attacker intercepts traffic and presents a different certificate — even one signed by a trusted CA — the app rejects the connection. This defends against man-in-the-middle (MITM) attacks.

**SPKI (Subject Public Key Info) pinning** is the recommended approach: instead of pinning the full certificate (which changes on every renewal), you pin the *public key*. The public key stays stable across certificate renewals as long as the server doesn't rotate its key pair.

The SPKI hash is computed as:

```
SHA-256( DER-encoded SubjectPublicKeyInfo structure ) → base64-encoded
```

### Relationship to the earlier POC

This project is the **MCP evolution** of `ssl-tasks-agents/`, which was a LiteLLM-based tool-calling agent with a hand-written orchestration loop. The core tool logic (`tools/ssl_pinning_hash_generator.py`) is identical — only the *exposure layer* has changed: instead of being wired directly into a custom agent loop, the tool is now served over the Model Context Protocol, making it available to any conforming AI client without any client-side code changes.

---

## 2. What is MCP and Why It Matters

### The Model Context Protocol

MCP is an open protocol (originally from Anthropic, now community-governed) that standardises how AI models discover and call external tools. It defines:

- **How tools are described** (name, description, input schema) — via a standard JSON schema format
- **How tools are invoked** — via a transport-level request/response protocol
- **How results are returned** — structured content the model can reason about
- **How servers are discovered** — via config files read by AI clients at startup

### Why MCP over a custom agent loop

| Aspect | Custom LiteLLM agent loop (`ssl-tasks-agents/`) | MCP server (`ssl-tasks-mcp-agents/`) |
|---|---|---|
| Tool availability | Only the one agent that imports the tool | Any MCP-compatible client (Claude, Cursor, Continue.dev, etc.) |
| Client code required | Yes — you write the orchestration loop | No — the client handles it |
| Tool discovery | Hardcoded in the agent | Automatic via MCP protocol |
| Transport | Python function call | SSE or Streamable-HTTP over the network |
| Interoperability | Single provider via LiteLLM | Universal across all MCP-aware clients |
| Maintenance | Each new client needs integration code | Write once, connect anywhere |

### Transports supported

This server supports two transports, selected at startup via the `MCP_TRANSPORT` environment variable:

| Transport | Value | Best for |
|---|---|---|
| **SSE** (Server-Sent Events) | `sse` (default) | Continue.dev, older MCP clients, streaming responses |
| **Streamable HTTP** | `streamable-http` | Claude Code, Claude Desktop, Cursor, newer clients |

Both transports serve the same tool — the only difference is the wire protocol.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AI Client Layer                         │
│                                                             │
│   Claude Code   Claude Desktop   Continue.dev   Gemini CLI  │
│       │               │               │              │      │
└───────┼───────────────┼───────────────┼──────────────┼──────┘
        │               │               │              │
        └───────────────┴───────────────┴──────────────┘
                                │
                    MCP Protocol (SSE or Streamable-HTTP)
                                │
┌───────────────────────────────▼─────────────────────────────┐
│                     MCP Server (server.py)                  │
│                                                             │
│   FastMCP framework                                         │
│   ├── Tool registry: generate_ssl_pin                       │
│   ├── Schema auto-generated from function signature         │
│   └── Transport handler (SSE / Streamable-HTTP)             │
│                                │                            │
└───────────────────────────────┼─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│              Tool Implementation (tools/)                   │
│                                                             │
│   ssl_pinning_hash_generator.py                             │
│   ├── _resolve_input()  ← URL / file path / PEM string      │
│   │       ├── HTTPS URL → TLS socket → DER bytes → PEM      │
│   │       ├── File path → read PEM/DER from disk            │
│   │       └── PEM string → use as-is                        │
│   │                                                         │
│   └── generate_ssl_pin()                                    │
│           └── OpenSSL pipeline (subprocess):                │
│               x509 -pubkey -noout                           │
│               │ pkey -pubin -outform der                    │
│               │ dgst -sha256 -binary                        │
│               │ enc -base64                                 │
│               └── {"sha256_hash": "8DKJU//..."}             │
└─────────────────────────────────────────────────────────────┘
```

### Request flow (example: Claude Code asking for a pin)

```
User: "Generate SSL pin for https://api.example.com"
    │
    ▼
Claude Code reads MCP config → discovers generate_ssl_pin tool
    │
    ▼
Claude (model) decides to call generate_ssl_pin(cert_input="https://api.example.com")
    │
    ▼  [MCP Protocol over Streamable-HTTP]
MCP Server receives tool call
    │
    ▼
ssl_pinning_hash_generator.generate_ssl_pin("https://api.example.com")
    ├── Opens TLS socket to api.example.com:443
    ├── Extracts DER certificate bytes from handshake
    ├── Converts to PEM, writes to temp file
    └── Runs OpenSSL pipeline → {"sha256_hash": "XyZ...=="}
    │
    ▼  [MCP Protocol — tool result]
MCP Server returns result to Claude Code
    │
    ▼
Claude formats the final answer:
  SHA-256 SPKI Hash: XyZ...==
  Android: <pin digest="SHA-256">XyZ...==</pin>
  iOS: "XyZ...=="
```

---

## 4. Technology Stack

| Component | Technology | Version | Role |
|---|---|---|---|
| MCP framework | `mcp[cli]` (FastMCP) | ≥ 1.27.1 | Server scaffolding, tool registry, transport handling |
| Python | CPython | 3.9+ | Runtime |
| SSL cert fetching | `ssl` + `socket` (stdlib) | — | TLS handshake, DER extraction |
| Hash computation | `openssl` CLI via `subprocess` | system openssl | SPKI hash pipeline |
| Transport — SSE | FastMCP built-in | — | Continue.dev and older clients |
| Transport — HTTP | FastMCP built-in (uvicorn) | — | Claude Code, Claude Desktop, Cursor |

**Why FastMCP over the raw MCP SDK?**
FastMCP is the high-level wrapper in the official `mcp` package. It auto-generates tool schemas from Python function signatures and docstrings, handles transport negotiation, and eliminates the boilerplate of the low-level SDK. For a single-tool server like this, it reduces `server.py` to ~25 lines.

**Why `openssl` CLI for hashing?**
The `openssl` binary is pre-installed on macOS and Linux. Using it via `subprocess` avoids adding `pyOpenSSL` or the `cryptography` library as a dependency. The pipeline is deterministic and easy to audit.

**Why `SSLContext.wrap_socket()` for cert fetching?**
`ssl.wrap_socket()` is deprecated in Python 3.x and does not support `server_hostname`, which is required for SNI (Server Name Indication). SNI is essential for any server that hosts multiple domains on a single IP address. `SSLContext.wrap_socket()` is the correct modern API.

---

## 5. Project Structure

```
ssl-tasks-mcp-agents/
├── server.py                          # MCP server entry point
├── start_server.sh                    # Convenience script to launch the server
├── tools/
│   ├── __init__.py
│   └── ssl_pinning_hash_generator.py  # Tool: fetches cert, computes SPKI hash
├── requirements.txt                   # Python dependencies (mcp[cli])
├── .venv/                             # Virtual environment (not in git)
├── .gitignore
└── README.md                          # This file
```

### `server.py`

Registers the `generate_ssl_pin` tool with FastMCP and starts the server. The transport (SSE vs Streamable-HTTP) is controlled by the `MCP_TRANSPORT` environment variable.

### `start_server.sh`

Convenience shell script that activates the virtual environment, validates prerequisites (venv present, port free), and launches `server.py` with the correct transport. Accepts two optional arguments: transport (`sse` or `http`) and port number. See [Section 9](#9-running-the-mcp-server) for full usage.

### `tools/ssl_pinning_hash_generator.py`

The actual tool logic. Framework-agnostic: it is a plain Python function with no MCP imports, making it testable in isolation and reusable in other contexts (e.g. the original LiteLLM agent, a CLI script, a unit test).

---

## 6. How the SSL Pinning Tool Works

The `generate_ssl_pin(cert_input: str)` function accepts three input forms:

### Input 1 — HTTPS URL

```python
generate_ssl_pin("https://api.example.com")
```

1. Strips the protocol and extracts `hostname`
2. Opens a raw TCP socket to `hostname:443`
3. Wraps it with `SSLContext.wrap_socket()` (TLS handshake)
4. Calls `getpeercert(binary_form=True)` → raw DER bytes (no HTTP request is made)
5. Converts DER to PEM for the OpenSSL pipeline

Certificate verification is intentionally disabled (`CERT_NONE`) so the tool can process self-signed and expired certificates. This is correct behaviour — the purpose is to *pin* the certificate, not to *validate* it.

### Input 2 — File path

```python
generate_ssl_pin("/path/to/certificate.pem")
```

Reads the PEM file directly from disk. Works with DER files too if they are renamed with a `.pem` extension after manual conversion.

### Input 3 — Raw PEM string

```python
generate_ssl_pin("-----BEGIN CERTIFICATE-----\nMIIF...\n-----END CERTIFICATE-----")
```

Uses the PEM string directly, no network or file I/O required.

### OpenSSL hash pipeline

All three paths converge at the same OpenSSL command chain:

```bash
openssl x509 -in cert.pem -pubkey -noout \
  | openssl pkey -pubin -outform der \
  | openssl dgst -sha256 -binary \
  | openssl enc -base64
```

| Stage | What it does |
|---|---|
| `x509 -pubkey -noout` | Extracts the public key from the certificate in PEM format |
| `pkey -pubin -outform der` | Re-encodes the public key as DER binary (this is the SPKI structure) |
| `dgst -sha256 -binary` | Computes the SHA-256 hash of the raw DER bytes |
| `enc -base64` | Base64-encodes the binary hash for embedding in config files |

The result is a string like `8DKJU//UFcNjiEPhNqsXQ1ceewuqgq7Rc1l+j99p9PE=`, ready to use in:

- **Android** `network_security_config.xml`: `<pin digest="SHA-256">8DKJU//...==</pin>`
- **iOS** `Info.plist` / `NSPinnedDomains`: `"8DKJU//...=="`
- **OkHttp** `CertificatePinner`: `.add("example.com", "sha256/8DKJU//...==")`

---

## 7. Prerequisites

Before running the server, verify these are available:

```bash
# Python 3.9 or later
python3 --version

# openssl on PATH (pre-installed on macOS and Linux)
which openssl
openssl version
```

No API keys are required — this server provides the *tool*, not the *model*. The AI client (Claude, Continue.dev, Gemini) provides its own model and handles authentication with its LLM provider independently.

---

## 8. Installation & Setup

### Step 1 — Clone the repository

```bash
git clone https://github.com/code2rise/ssl-pinning-mcp-agent
cd ssl-tasks-mcp-agents
```

### Step 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` contains:
```
mcp[cli]>=1.27.1
```

The `[cli]` extra pulls in `uvicorn` (for Streamable-HTTP transport) and the `mcp` development CLI tools alongside the core SDK.

### Step 4 — Verify the installation

```bash
python3 -c "from mcp.server.fastmcp import FastMCP; print('FastMCP OK')"
# Expected output: FastMCP OK
```

---

## 9. Running the MCP Server

The recommended way to start the server is `start_server.sh` — it activates the virtual environment, checks that the target port is free, and launches `server.py` with the correct transport in one step.

### `start_server.sh` — usage

```bash
# Make executable (first time only)
chmod +x start_server.sh

# SSE transport (default) — for Continue.dev and older MCP clients
./start_server.sh

# Streamable-HTTP transport — for Claude Code and Claude Desktop
./start_server.sh http

# Explicit SSE
./start_server.sh sse

# Custom port (transport + port)
./start_server.sh http 9000
./start_server.sh sse 9000
```

### What the script does

1. Resolves the transport from the first argument (`sse` default, `http` for Streamable-HTTP)
2. Checks that `.venv/` exists — prints setup instructions and exits if missing
3. Checks that the target port is free — exits with a clear message if occupied
4. Activates the virtual environment
5. Launches `server.py` with `MCP_TRANSPORT` and `PORT` set

### Startup output

```
  SSL Pinning MCP Server
  ──────────────────────────────────────────
  Transport : streamable-http
  Endpoint  : http://localhost:8000/mcp
  Ctrl+C    : stop the server
  ──────────────────────────────────────────

INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Endpoints by transport

| Transport | Command | Endpoint |
|---|---|---|
| SSE | `./start_server.sh` | `http://localhost:8000/sse` |
| Streamable-HTTP | `./start_server.sh http` | `http://localhost:8000/mcp` |

### Manual launch (without the script)

If you prefer to launch directly:

```bash
source .venv/bin/activate

# SSE
python3 server.py

# Streamable-HTTP
MCP_TRANSPORT=streamable-http python3 server.py

# Custom port
MCP_TRANSPORT=streamable-http PORT=9000 python3 server.py
```

### Verifying the server is running

Use the `mcp` Python client to confirm the tool is discoverable and callable:

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test():
    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            result = await session.call_tool("generate_ssl_pin", {"cert_input": "https://github.com"})
            print(result.content[0].text)

asyncio.run(test())
```

For SSE, replace `streamablehttp_client` with `sse_client` from `mcp.client.sse` and connect to `http://localhost:8000/sse`.

---

## 10. Client Integration

### 10.1 Claude Code (CLI)

Claude Code supports multiple configuration approaches for MCP servers. The **recommended approach** (and what was used in this project) is `~/.mcp.json` + `enabledMcpjsonServers`. See [Section 15](#15-claude-code-mcp-configuration-priority-order--actual-setup) for the full priority order and step-by-step walkthrough.

#### Approach A — `~/.mcp.json` (Recommended, used in this project)

**Step 1 — Start the server** (Streamable-HTTP transport):

```bash
cd /path/to/ssl-tasks-mcp-agents
./start_server.sh http
```

**Step 2 — Add the server to `~/.mcp.json`** (create the file if it doesn't exist):

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

**Step 3 — Enable the server for your project** in `<project>/.claude/settings.local.json`:

```json
{
  "enabledMcpjsonServers": ["ssl-pinning"]
}
```

**Step 4 — Use it in any Claude Code session in that project:**

```
> Generate SSL pin for https://api.example.com
```

Claude will automatically discover and call the `generate_ssl_pin` tool.

#### Approach B — `~/.claude/settings.json` (older, always-on)

Add directly under `mcpServers` in `~/.claude/settings.json` to make the server available globally in all projects without needing `enabledMcpjsonServers`:

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

#### Approach C — Claude Code CLI command

```bash
claude mcp add ssl-pinning --transport http http://localhost:8000/mcp
```

#### Approach D — Stdio transport (no background server needed)

Claude Code launches the server as a subprocess — no need to keep a server running separately:

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "type": "stdio",
      "command": "/path/to/ssl-tasks-mcp-agents/.venv/bin/python3",
      "args": ["/path/to/ssl-tasks-mcp-agents/server.py"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

---

### 10.2 Claude Desktop

Claude Desktop uses a JSON config file to register MCP servers.

**Config file location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Step 1 — Edit `claude_desktop_config.json`:**

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "command": "/path/to/ssl-tasks-mcp-agents/.venv/bin/python3",
      "args": [
        "/path/to/ssl-tasks-mcp-agents/server.py"
      ],
      "env": {
        "MCP_TRANSPORT": "streamable-http"
      }
    }
  }
}
```

> Replace `/path/to/ssl-tasks-mcp-agents` with the absolute path on your machine.

**Step 2 — Restart Claude Desktop.**

Claude Desktop will launch the MCP server automatically when it starts. You'll see a hammer icon (🔨) in the chat interface indicating available tools.

**Step 3 — Verify in Claude Desktop:**

Type: *"What tools do you have available?"*

Claude should list `generate_ssl_pin`.

**Step 4 — Use it:**

```
Generate the SSL pinning hash for https://api.stripe.com and give me the
network_security_config.xml snippet.
```

---

### 10.3 Continue.dev (VS Code / JetBrains)

Continue.dev uses the SSE transport. The server must be running before Continue.dev connects.

**Step 1 — Start the server in SSE mode (default):**

```bash
./start_server.sh
# Server listening at http://localhost:8000/sse
```

**Step 2 — Edit `~/.continue/config.json`:**

```json
{
  "models": [
    {
      "title": "Claude Sonnet",
      "provider": "anthropic",
      "model": "claude-sonnet-4-6",
      "apiKey": "sk-ant-..."
    }
  ],
  "tools": [
    {
      "type": "mcp",
      "transport": {
        "type": "sse",
        "url": "http://localhost:8000/sse"
      }
    }
  ]
}
```

**Step 3 — Reload Continue.dev** (Cmd+Shift+P → "Continue: Reload").

**Step 4 — Use it in the Continue chat panel:**

```
@ssl-pinning Generate SSL pin for https://firebase.googleapis.com
```

Or naturally:

```
What's the SHA-256 SPKI hash for https://api.openai.com? Give me the OkHttp
CertificatePinner line.
```

**JetBrains note:** The Continue.dev JetBrains plugin uses the same `~/.continue/config.json` — no additional steps required.

---

### 10.4 Gemini CLI / Google AI Studio

Gemini CLI (the `gemini` command-line tool) supports MCP servers via its configuration file.

**Step 1 — Start the server:**

```bash
./start_server.sh http
```

**Step 2 — Edit `~/.gemini/settings.json`** (create if it doesn't exist):

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "httpUrl": "http://localhost:8000/mcp"
    }
  }
}
```

**Step 3 — Start Gemini CLI:**

```bash
gemini
```

Gemini CLI discovers MCP servers at startup and lists available tools.

**Step 4 — Use it:**

```
Generate the SSL pinning hash for https://accounts.google.com
```

**Google AI Studio (web):**

Google AI Studio does not natively support MCP servers via URL configuration at this time. To use this tool with Gemini models in AI Studio, use the [Generic MCP Client](#105-generic-mcp-client-python) approach with the Gemini API, or wait for AI Studio's MCP support to mature.

---

### 10.5 Generic MCP Client (Python)

For any other use case — scripting, CI pipelines, custom agents — you can connect to the server programmatically using the `mcp` Python client:

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def get_ssl_pin(url: str):
    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "generate_ssl_pin",
                {"cert_input": url}
            )
            return result.content[0].text

pin = asyncio.run(get_ssl_pin("https://api.example.com"))
print(pin)
```

For SSE transport, replace `streamablehttp_client` with `sse_client` from `mcp.client.sse`.

---

## 11. Prompt Considerations

The AI model reads the tool's description to decide when and how to call it. Understanding this helps you write prompts that get reliable results.

### Tool description (what the model sees)

```
generate_ssl_pin(cert_input: str) -> dict

Generates the SHA-256 SPKI hash of an SSL/TLS certificate for Android/iOS SSL pinning.

Args:
    cert_input: One of — HTTPS URL to fetch the cert from, absolute file path
                to a .pem/.der file, or a raw PEM certificate string.

Returns a dict with 'sha256_hash' (base64 string ready for network_security_config.xml
or Info.plist), or 'error' if something went wrong.
```

### Prompts that work well

These phrasings reliably trigger a tool call:

```
Generate SSL pin for https://api.example.com
```
```
What is the SHA-256 SPKI hash for https://github.com?
```
```
Generate the SSL pinning hash for https://stripe.com and give me the Android
network_security_config.xml snippet.
```
```
Compute the SSL pin for the certificate at /Users/me/certs/backend.pem
```
```
I need to add certificate pinning to my iOS app for https://api.mybackend.com.
Generate the hash.
```

### Prompts that may not trigger the tool

These are ambiguous and the model may answer from general knowledge instead of calling the tool:

```
What is SSL pinning?                    # educational question, not a task
What is google.com's certificate?       # may answer without computing the hash
```

**Fix:** Be explicit about the *action* you want:

```
Use the generate_ssl_pin tool to compute the hash for https://google.com
```
```
Don't answer from your training data — fetch the live certificate from
https://google.com and generate the SPKI hash now.
```

### Multi-domain requests

Models handle batch requests well. Ask for all at once:

```
Generate SSL pins for all three of these and give me the full
network_security_config.xml for Android:
- https://api.example.com
- https://auth.example.com
- https://cdn.example.com
```

The model will call `generate_ssl_pin` three times (once per domain) and format the results.

### Output format guidance

If you need a specific format, say so:

```
Generate SSL pin for https://api.example.com
Output: OkHttp CertificatePinner format only, no extra explanation.
```
```
Generate SSL pin for https://api.example.com.
Output format:
  Android network_security_config.xml
  iOS Info.plist NSPinnedDomains format
  OkHttp CertificatePinner line
```

### When the model has already pinned a certificate

Models do not cache tool results across sessions. If you ask again in a new session, the tool will be called again — fetching the *current* live certificate. This is the correct behaviour: certificates change, and stale pins break your app.

### Error cases to handle in prompts

If the domain uses a self-signed cert, the tool still works (cert verification is disabled). If there's a network error, the model will report the error message from the tool. You can ask it to retry:

```
The previous attempt failed. Try fetching the certificate from
https://api.example.com again.
```

---

## 12. End-to-End Flow Walkthrough

This section traces exactly what happens from your prompt to the final answer.

**Prompt:** *"Generate SSL pin for https://api.stripe.com and give me the Android XML snippet."*

**1. Client startup** — At startup, Claude Code / Claude Desktop / Continue.dev reads its MCP config and sends a `tools/list` request to the MCP server. The server responds with the schema of `generate_ssl_pin`.

**2. Model inference** — Your prompt is sent to the LLM (Claude, Gemini, etc.) along with the tool schema. The model decides to call the tool rather than answer from training data.

**3. Tool invocation** — The client sends a `tools/call` request over MCP:
```json
{
  "name": "generate_ssl_pin",
  "arguments": { "cert_input": "https://api.stripe.com" }
}
```

**4. Server execution** — `server.py` receives the call and routes it to `ssl_pinning_hash_generator.generate_ssl_pin("https://api.stripe.com")`.

**5. Certificate fetch** — A TLS socket connects to `api.stripe.com:443`. The DER-encoded certificate is extracted from the handshake. No HTTP request is made.

**6. Hash computation** — The DER bytes are converted to PEM, written to a temp file, and passed through the OpenSSL pipeline. The temp file is deleted after.

**7. Result** — The tool returns `{"sha256_hash": "15C...=="}`.

**8. MCP response** — The server wraps this in an MCP tool result and sends it back to the client.

**9. Final answer** — The model sees the tool result and generates:
```
SHA-256 SPKI Hash: 15C...==

Android network_security_config.xml:
<network-security-config>
  <domain-config>
    <domain includeSubdomains="true">api.stripe.com</domain>
    <pin-set>
      <pin digest="SHA-256">15C...==</pin>
    </pin-set>
  </domain-config>
</network-security-config>
```

---

## 13. Evolution from Tool-Calling Agent to MCP

The `ssl-tasks-agents/` directory contains the first version of this system — a self-contained Python agent with a hand-written tool-calling loop. Comparing the two architectures shows why MCP is the right next step.

### Tool-calling agent (`ssl-tasks-agents/agent.py`)

```
User prompt
    │
    ▼
agent.py                      ← you wrote this
  ├── litellm.completion()    ← you wire the LLM
  ├── Inspect response        ← you parse tool_calls
  ├── Call the tool           ← you call the function
  ├── Append result to msgs   ← you manage history
  └── Loop                    ← you implement the loop
    │
    ▼
Final answer
```

- Works, but every new client (Claude, GPT-4o, Gemini, Ollama) needed its own wiring
- Tool is not discoverable — only this agent knows about it
- Ollama required a special two-call workaround because local models loop on tool results

### MCP server (`ssl-tasks-mcp-agents/server.py`)

```
User prompt (in any MCP client)
    │
    ▼
AI Client                     ← built by Anthropic / Google / Continue.dev / etc.
  ├── Discovers tools via MCP
  ├── Calls tool via MCP
  └── Handles loop internally
    │
    ▼  MCP protocol
server.py                     ← you wrote 25 lines
  └── generate_ssl_pin()      ← same tool logic
    │
    ▼
Final answer
```

- The client handles the agentic loop, history management, and model wiring
- The tool is discoverable by any MCP-compatible client
- No Ollama workaround needed — the client handles model-specific quirks
- Adding a new client = adding 5 lines to a config file

---

## 14. Known Limitations & Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: mcp` | venv not activated or deps not installed | `source .venv/bin/activate && pip install -r requirements.txt` |
| `openssl: command not found` | openssl not on PATH | Install via Homebrew: `brew install openssl` |
| Tool not visible in Claude Code | MCP config not applied or wrong transport | Restart Claude Code; confirm `type: "http"` and correct URL |
| Tool not visible in Continue.dev | SSE URL incorrect or server not running | Start server with default transport; check `http://localhost:8000/sse` |
| `Connection refused` | Server not running | Run `python3 server.py` in the mcp-agents directory |
| Self-signed cert hash error | openssl version mismatch | Verify `openssl version`; macOS ships LibreSSL, which works |
| Cert pin expires / mismatches | Server rotated its certificate | Re-run the tool to get the updated hash; add a backup pin |
| Model answers without calling the tool | Prompt too vague or educational | Rephrase with explicit action: *"Generate the SSL pin for..."* |
| Port 8000 already in use | Another process on the same port | `PORT=9000 python3 server.py` and update client config accordingly |

---

## 15. Claude Code MCP Configuration: Priority Order & Actual Setup

This section documents exactly how the `ssl-pinning` MCP server was integrated with Claude Code in this system, and explains the full configuration hierarchy so you can replicate or adapt it.

---

### 15.1 MCP Configuration File Locations & Priority Order

Claude Code reads MCP server definitions from multiple locations. When the same server name appears in more than one file, the **highest-priority file wins**. Files are evaluated in this order (1 = highest priority):

| Priority | File | Scope | Notes |
|---|---|---|---|
| 1 | `/etc/claude/settings.json` | Enterprise / machine-wide | Managed by MDM or IT policy; read-only to users |
| 2 | `~/.claude/settings.json` → `mcpServers` | User-global | Applies to every project on the machine |
| 3 | `<project>/.claude/settings.json` → `mcpServers` | Project | Committed to the repo; shared with the team |
| 4 | `<project>/.claude/settings.local.json` → `mcpServers` | Project-local | **Not** committed; personal overrides on top of project settings |
| 5 | `~/.mcp.json` → `mcpServers` | User-global MCP registry | Dedicated MCP file; shared across all projects |
| 6 | `<project>/.mcp.json` → `mcpServers` | Project MCP registry | Dedicated MCP file; project-scoped |

> **`settings.json` vs `.mcp.json`** — both can define `mcpServers`. The `.mcp.json` files are purpose-built for MCP and are the recommended approach going forward. The `mcpServers` key inside `settings.json` is the older approach and still works, but `.mcp.json` keeps MCP config separate from general Claude Code preferences.

---

### 15.2 The `enabledMcpjsonServers` Filter

Entries in `.mcp.json` files are **not automatically active**. Each project opts in via the `enabledMcpjsonServers` array in its `.claude/settings.local.json`:

```json
{
  "enabledMcpjsonServers": ["ssl-pinning"]
}
```

- Only server names listed here are loaded from `.mcp.json` for that project.
- If the array is absent or empty, no `.mcp.json` servers are loaded for the project.
- Servers defined directly under `mcpServers` in `settings.json` are not affected by this filter — they are always loaded.

**Why this design?** A shared `~/.mcp.json` may list many servers (for different projects). The filter prevents every server being injected into every Claude Code session regardless of relevance.

---

### 15.3 Step-by-Step: Actual Setup Performed

This documents exactly what was done to connect `ssl-pinning` to Claude Code in the `~/Workspace/AI` project.

#### Step 1 — Build the MCP server

`server.py` was written using FastMCP. It registers one tool (`generate_ssl_pin`) and exposes it over either SSE or Streamable-HTTP depending on the `MCP_TRANSPORT` environment variable.

```
~/Workspace/AI/ssl-tasks-mcp-agents/
├── server.py                         ← FastMCP server (25 lines)
├── start_server.sh                   ← launch helper
├── tools/
│   └── ssl_pinning_hash_generator.py ← tool logic (framework-free)
└── requirements.txt                  ← mcp[cli]>=1.27.1
```

#### Step 2 — Create the virtual environment and install dependencies

```bash
cd ~/Workspace/AI/ssl-tasks-mcp-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`:
```
mcp[cli]>=1.27.1
```

The `[cli]` extra includes `uvicorn` (required for Streamable-HTTP) and the `mcp` developer CLI tools.

#### Step 3 — Start the server with Streamable-HTTP transport

Claude Code uses the Streamable-HTTP transport (not SSE). The server was started with:

```bash
./start_server.sh http
```

This sets `MCP_TRANSPORT=streamable-http` and launches `server.py` with `uvicorn` on port 8000.

```
  SSL Pinning MCP Server
  ──────────────────────────────────────────
  Transport : streamable-http
  Endpoint  : http://localhost:8000/mcp
  Ctrl+C    : stop the server
  ──────────────────────────────────────────
```

The server must be running before Claude Code starts (or before a session begins) for the tools to be available.

#### Step 4 — Register the server in `~/.mcp.json`

The file `~/.mcp.json` was created at the home directory level to make the server available globally (across all Claude Code projects on the machine):

```json
{
  "mcpServers": {
    "ssl-pinning": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

**File location:** `~/.mcp.json`

- `type: "http"` selects the Streamable-HTTP transport (matches `./start_server.sh http`)
- `url` points to the running server's MCP endpoint

#### Step 5 — Opt the workspace into the server via `enabledMcpjsonServers`

Creating the entry in `~/.mcp.json` alone is not enough — each project must explicitly enable servers from `.mcp.json` files. The file `.claude/settings.local.json` was created inside the `~/Workspace/AI` project directory:

**File location:** `~/Workspace/AI/.claude/settings.local.json`

```json
{
  "enabledMcpjsonServers": [
    "ssl-pinning"
  ]
}
```

This tells Claude Code: *"For this project, load the `ssl-pinning` server from the `.mcp.json` registry."*

This file is `.local.json` (not committed to git) because it is a personal machine-level opt-in. Team members with different local servers or ports would have their own version.

#### Step 6 — Verify the connection

To confirm Claude Code picked up the server, a new Claude Code session was started in `~/Workspace/AI` and a tool call was issued:

```
> Generate SSL pin for https://google.com
```

Claude Code resolved the tool via MCP, called `generate_ssl_pin`, and returned the hash.

To verify the server is reachable independently:

```bash
# Check the server process is running on port 8000
lsof -iTCP:8000 -sTCP:LISTEN

# Make a direct JSON-RPC call (initialize → tools/call)
SESSION=$(curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  -D - 2>&1 | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"generate_ssl_pin","arguments":{"cert_input":"https://google.com"}}}'
```

---

### 15.4 Configuration Summary

```
~/.mcp.json                          ← defines the server (user-global registry)
    └── ssl-pinning: http://localhost:8000/mcp

~/Workspace/AI/
├── .claude/
│   └── settings.local.json          ← enables ssl-pinning for this workspace only
│       └── enabledMcpjsonServers: ["ssl-pinning"]
│
└── ssl-tasks-mcp-agents/
    ├── server.py                    ← the MCP server
    ├── start_server.sh              ← starts server on port 8000 (Streamable-HTTP)
    └── tools/
        └── ssl_pinning_hash_generator.py
```

**Decision rationale:**

- `~/.mcp.json` was chosen over `~/.claude/settings.json` (`mcpServers` key) to keep MCP server definitions separate from general Claude Code preferences.
- User-global (`~/.mcp.json`) was chosen over project-local (`.mcp.json` inside the repo) because the server is a shared infrastructure concern — not specific to one sub-project within `~/Workspace/AI`.
- `settings.local.json` (not `settings.json`) was used for `enabledMcpjsonServers` because the opt-in is machine-specific and should not be committed to git.

---

### 15.5 Quick Reference: When to Use Which Config File

| Goal | Recommended file |
|---|---|
| Register a server available to all projects on the machine | `~/.mcp.json` |
| Register a server specific to one project (team-shared) | `<project>/.mcp.json` |
| Register a server via the older `settings.json` approach | `~/.claude/settings.json` → `mcpServers` |
| Opt a project into servers from `.mcp.json` | `<project>/.claude/settings.local.json` → `enabledMcpjsonServers` |
| Set environment variables for Claude Code sessions | `<project>/.claude/settings.json` → `env` |
| Override project settings locally (personal, not committed) | `<project>/.claude/settings.local.json` |
