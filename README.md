# mcp-intercept

**A lightweight WebSocket-based interceptor for local Model Context Protocol (MCP) communication.**

`mcp-intercept` lets you observe and relay local MCP traffic between a stdio-based MCP process and any MCP-compatible host, such as Claude Desktop. It runs a small local WebSocket bridge that routes messages through an HTTP proxy, enabling inspection, debugging, or modification of protocol exchanges.

---

## 🧠 Overview

`mcp_intercept.py` launches an MCP server process (for example, a Node or Python script that implements MCP over stdio). It then starts a local WebSocket server and connects to it through an HTTP proxy such as `Burp`. All MCP messages between the client and server pass through this bridge, making it possible to inspect or manipulate them.

---

## 📈 Architecture Diagram

> **[Diagram placeholder]**  
> _Insert an image (SVG/PNG) showing: Claude Desktop (MCP client) ↔ mcp-intercept (WS bridge) ↔ optional HTTP proxy ↔ Your MCP server (stdio)._

---

## ⚙️ Installation & Setup

### 1) Clone the repository

```bash
git clone https://github.com/gabriel-sztejnworcel/mcp-intercept
cd mcp-intercept
```

### 2) Create and activate a virtual environment

#### 🪟 On Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
```

#### 🍎 On macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

---

## 🧑‍💻 Usage

You need to configure your MCP host to run `mcp_intercept.py` as an MCP server, and pass the command for your target MCP server:

```bash
path/to/mcp-intercept/.venv/bin/python mcp_intercept.py --proxy-port 8080 path/to/mcp-server mcp-server-args
```

- `path/to/mcp-server mcp-server-args` → the MCP process to run and intercept  
- `--proxy-port 8080` → optional (default `8080`); the local HTTP proxy that `mcp-intercept` will route through

Use any WebSocket-capable proxy like **Burp Suite** to inspect the traffic on the specified port.

---

## 🧩 Configure as an MCP server in Claude Desktop

You can make `mcp-intercept` behave like a normal MCP server so Claude Desktop launches it automatically.

### 1) Locate the Claude MCP config

- **macOS:** `~/Library/Application Support/Claude/mcp.json`  
- **Windows:** `%APPDATA%\Claude\mcp.json`

### 2) Add an entry for `mcp-intercept`

```json
{
  "servers": {
    "mcp-intercept": {
      "command": "python",
      "args": [
        "/path/to/mcp-intercept/mcp_intercept.py",
        "node",
        "/path/to/your-mcp-server.js"
      ]
    }
  }
}
```

> Replace `/path/to/...` with your actual paths.

### 3) Restart Claude Desktop

Upon restart, Claude will launch `mcp-intercept`, which spawns your MCP server and routes communication through the interceptor (and proxy, if configured).

---

## 🧠 How It Works

1. Spawns your target process (e.g., `node mcp-server.js`) with `stdin`/`stdout` piped.  
2. Launches a local WebSocket server bound to `127.0.0.1:<random_port>`.  
3. Starts a WebSocket client that connects to that server via an HTTP proxy (default `127.0.0.1:8080`).  
4. Logs go to `stderr`, keeping protocol bytes clean on `stdout`.

---

## 📜 License

MIT License © 2025 Gabriel Sztejnworcel
