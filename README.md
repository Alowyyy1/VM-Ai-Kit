# VirtualMachine AI Kit (VM-Ai-Kit)

VirtualMachine AI Kit is an isolated reverse engineering, malware analysis, and dynamic debugging environment controlled entirely by AI coding agents via the Model Context Protocol (MCP).

It allows an AI agent (such as Google Antigravity, OpenCode, or OpenAI Codex) running on a host workstation to inspect binaries, decompile code to pseudocode, analyze memory injections, unpack protected executables, and control a Windows virtual machine over a single open TCP port (37075).

---

## Capabilities

1. Static Binary Analysis:
   - Automated identification of compilers, packers, protectors, and libraries using Detect It Easy (DIE 3.10).
   - Deep capability extraction using Mandiant Capa (over 1,000 detection rules).
   - Low-level Portable Executable (PE) parsing: headers, section entropy, rich headers, import/export tables, TLS callbacks, resources, and overlay detection.
   - String extraction, pattern/AOB search with wildcards, and Capstone-based x86/x64 disassembly.

2. Decompilation and Pseudocode:
   - Decompilation of .NET assemblies into clean C# pseudocode using dnSpy.Console.
   - Native binary disassembly, function discovery, and metadata analysis via Rizin.
   - Go binary symbol recovery (packages, functions, types) using GoReSym.

3. Dynamic Debugging and Anti-Anti-Debug:
   - Integrated x64dbg (x64 and x32) automated via an internal REST API bridge.
   - Pre-installed ScyllaHide plugin: hides debugging flags (PEB BeingDebugged, NtGlobalFlag), hooks RDTSC, and patches anti-debug vectors.
   - Full breakpoint management (software and hardware), step-in, step-over, memory reading/writing, module dumping, and register manipulation.

4. In-Memory Unpacking and Process Hollowing Detection:
   - PE-sieve and HollowsHunter integration: detects and dumps hidden, unmapped, or hollowed executable code directly from running process memory without manual unpacker scripting.
   - Scylla Import Address Table (IAT) reconstruction.

5. Full Operating System and GUI Control:
   - Command execution via CMD and PowerShell.
   - Full filesystem access: chunked binary upload/download, file hashing, zip/unzip, and directory traversal.
   - Graphical desktop automation: high-speed screen capture, pixel sampling, mouse movement, click/drag events, keyboard keystrokes, and window management.

---

## Architecture

Communication is multiplexed over a single network boundary:

- Host Machine (Workstation):
  Runs your AI client (Google Antigravity, OpenCode, OpenAI Codex). Connects to `http://<VM_IP>:37075/mcp` using FastMCP streamable HTTP transport with Bearer token authentication.

- Virtual Machine (Guest):
  Runs the FastMCP server (`vm_agent.server`) listening on `0.0.0.0:37075`.
  The x64dbg automation plugin binds internally to loopback `127.0.0.1:27042` inside the VM. The agent forwards all debugging requests internally. Only port 37075 needs to be forwarded from the VM.

---

## Quick Start Guide

### Step 1: Virtual Machine Setup

1. Copy the repository contents into the Windows machine (or `git clone` it).
2. Right-click `INSTALL_AND_START.bat` and select "Run as Administrator".
3. The script will automatically:
   - Add the kit directory to Windows Defender exclusions.
   - Install Python 3.12 and offline Python dependencies if missing.
   - Install Node.js LTS if missing.
   - Configure x64dbg with ScyllaHide and the MCP automation plugin.
   - Register an autostart task in Windows Task Scheduler (starts on user logon).
   - Open TCP port 37075 in Windows Firewall.
   - Display the virtual machine's IP address and start the server.

### Step 2: Port Forwarding (Host Configuration)

If the virtual machine uses NAT networking:

- VirtualBox:
  VM Settings -> Network -> Adapter 1 (NAT) -> Advanced -> Port Forwarding:
  - Protocol: TCP
  - Host Port: 37075
  - Guest Port: 37075
  - Host IP: 127.0.0.1

- VMware Workstation:
  Edit -> Virtual Network Editor -> VMnet8 (NAT) -> NAT Settings -> Port Forwarding -> Add:
  - Host Port: 37075
  - Type: TCP
  - Virtual Machine IP: <Guest_VM_IP>
  - Virtual Machine Port: 37075

If using Bridged Adapter networking, no port forwarding is required; connect directly to the guest IP.

### Step 3: Host Client Registration

On the host machine, run the appropriate batch script from the `host` directory:

- Run `INSTALL_ALL.bat` to configure Google Antigravity, OpenCode, and Codex simultaneously.
- Or run individual installers:
  - `INSTALL_ANTIGRAVITY.bat`
  - `INSTALL_OPENCODE.bat`
  - `INSTALL_CODEX.bat`
- Run `TEST_CONNECTION.bat` to test connectivity against `http://<VM_IP>:37075/healthz`.

---

## MCP Tool Reference (103 Tools)

### Static Analysis and Decompilation
- `die_scan(path, deep=True, show_entropy=False, timeout=60)`: Scans with Detect It Easy; returns compiler, linker, packer, libraries, and section entropy.
- `capa_scan(path, timeout=300, json_format=True)`: Evaluates Mandiant Capa heuristics against 1,000+ rules.
- `decompile_dotnet(path, type_name="", output_dir="", timeout=180)`: Decompiles .NET assemblies to C# pseudocode via dnSpy.Console.
- `go_symbols(path, timeout=60)`: Extracts symbols, packages, and types from stripped Go binaries.
- `pe_info(path)`: Deep inspection of PE headers, sections, imports, exports, TLS, and overlays.
- `pe_strings(path, min_length=6, encoding="ascii", limit=1000)`: Extracts ASCII or UTF-16 strings.
- `pe_search(path, pattern, limit=100)`: Searches raw bytes using text or hex wildcards (e.g. `E8 ?? ?? ?? ?? 48 89`).
- `pe_disasm(path, offset=0, rva=0, count=30, bits=64)`: Capstone disassembly at raw offset or RVA.
- `pe_entropy(path, offset=0, length=0)`: Computes Shannon entropy of files or slices.
- `pe_hexdump(path, offset=0, length=256)`: Formatted hex and ASCII dump.

### Traffic Debugger (mitmproxy)
- `net_proxy_install_cert()`, `net_proxy_start(port=8080, web_ui=False, set_system_proxy=True)`, `net_proxy_stop()`, `net_proxy_status()`, `net_proxy_flows(limit, host_filter)`, `net_proxy_flow_detail(flow_id)`, `net_proxy_clear()`: capture and inspect HTTP/HTTPS traffic.

### GUI Orientation
- `screen_capture(..., grid=True, grid_step=100)`: screenshot with a labelled pixel grid.
- `ui_desktop_icons(filter)`: exact coordinates of desktop icons.

### Debugging and Runtime Unpacking
- `dbg_launch(path, args=[], suspend=True)`: Launches an executable inside x64dbg.
- `dbg_attach(pid)`: Attaches x64dbg to an existing process.
- `dbg_hide_debugger()`: Activates ScyllaHide anti-anti-debug hooks.
- `dbg_set_breakpoint(address, type="software")`: Sets software or hardware breakpoints.
- `dbg_run()`, `dbg_pause()`, `dbg_step(type="into")`: Controls execution flow.
- `dbg_read_memory(address, size)`, `dbg_write_memory(address, data_hex)`: Inspects and modifies target process memory.
- `dbg_dump_module(module_name, output_path)`: Dumps a loaded PE module from memory.
- `dbg_registers()`: Retrieves CPU register states (RAX, RBX, RIP, EFLAGS, etc.).
- `dbg_callstack()`: Retrieves the current thread stack frames.
- `dbg_command(cmd)`: Executes a native x64dbg script command.
- `scan_memory_hollows(pid=0, timeout=120)`: Scans processes for injected or hollowed code via PE-sieve or HollowsHunter.

### System, Filesystem, and GUI
- `sys_exec(cmd, timeout=60)`: Executes a shell command via cmd.exe.
- `sys_powershell(script, timeout=60)`: Executes a PowerShell script block.
- `sys_processes()`: Lists running processes with PID, architecture, and memory usage.
- `sys_kill(pid)`: Terminates a process.
- `sys_info()`: Returns operating system, CPU, memory, and environment details.
- `fs_read_bytes(path, offset=0, length=0)`: Reads binary files (base64 encoded).
- `fs_write_bytes(path, data, mode="overwrite")`: Writes or appends binary data.
- `fs_list(path)`: Lists directory contents with sizes and modification times.
- `fs_zip(src_path, dst_zip)`, `fs_unzip(zip_path, dst_dir)`: Compresses and decompresses archives.
- `screen_capture()`: Captures the VM desktop and returns an inline PNG image.
- `input_click(x, y, button="left")`: Injects mouse click events.
- `input_type(text)`: Types keyboard text.
- `input_key(key, down=True)`: Presses or releases a specific virtual key.
- `win_list()`: Lists all visible and background application windows.
- `win_focus(handle_or_title)`: Brings a specific window to the foreground.

---

## Repository Structure

```
VM-Ai-Kit/
├── vm_agent/                  # FastMCP Agent Server implementation
│   ├── server.py              # Main entry point and HTTP endpoint
│   ├── config.py              # Configuration and path resolution
│   ├── t_static.py            # Static analysis, DIE, Capa, dnSpy tools
│   ├── t_dbg.py               # x64dbg and ScyllaHide debugging tools
│   ├── t_system.py            # Shell execution and process management
│   ├── t_files.py             # Filesystem operations
│   ├── t_ui.py                # Screen capture and input injection
│   ├── pe.py                  # Low-level PE parser
│   ├── winapi.py              # Windows API bindings
│   └── x64dbg.py              # x64dbg REST client
├── host/                      # Host machine setup and client configuration
│   ├── host_config.example.json  # Template; installer creates host_config.json (git-ignored)
│   ├── INSTALL_ALL.bat        # Configures Antigravity, OpenCode, and Codex
│   ├── INSTALL_ANTIGRAVITY.bat
│   ├── INSTALL_OPENCODE.bat
│   ├── INSTALL_CODEX.bat
│   ├── TEST_CONNECTION.bat    # Tests connection to VM /healthz
│   ├── SET_IP_AND_TOKEN.bat   # Interactive IP and token updater
│   └── antigravity_schemas/   # 103 JSON tool schemas for Antigravity
├── scripts/                   # Debugger scripts and snapshot guides
├── config/                    # Default and example agent configurations
├── install-vm.ps1             # Main VM installer script (PowerShell)
├── INSTALL_AND_START.bat      # One-click VM setup launcher
├── START_AGENT.bat            # Manual agent start
├── STOP_AGENT.bat             # Manual agent stop
└── README.md                  # Documentation
```

---

## License

This project is licensed under the Apache License 2.0. See the LICENSE file for details.
