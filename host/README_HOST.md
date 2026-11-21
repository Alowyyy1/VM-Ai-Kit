# VirtualMachine AI Kit — Хостовая часть (Host Part)

Пакет для подключения ИИ-агентов (**Google Antigravity**, **OpenCode**, **OpenAI Codex**, Claude Code, Cursor) на основном компьютере к изолированной виртуальной машине для безопасного реверса, декомпиляции, отладки и анализа вредоносного ПО.

---

## ⚡ Быстрый старт в 2 шага

### Шаг 1. Настройка виртуальной машины (на хосте)
Убедитесь, что порт **37075** проброшен с хоста в виртуальную машину.

- **VirtualBox (NAT)**:
  1. Выберите VM -> Настройки -> Сеть -> Адаптер 1 (NAT) -> Дополнительно -> Проброс портов.
  2. Добавьте правило:
     - Порт хоста: `37075`
     - Порт гостя: `37075`
     - IP хоста: `127.0.0.1`

- **VMware Workstation (NAT)**:
  1. Edit -> Virtual Network Editor -> Выберите NAT (VMnet8) -> NAT Settings.
  2. Port Forwarding -> Add:
     - Host port: `37075`
     - Type: `TCP`
     - Virtual machine IP: `<IP_Виртуалки>`
     - Virtual machine port: `37075`

- **Режим сетевого моста (Bridged)**:
  Если виртуалка подключена через сетевой мост и имеет свой IP в вашей локальной сети (например `192.168.1.150`):
  1. Запустите на хосте файл **`SET_IP_AND_TOKEN.bat`** и укажите IP виртуалки.

### Шаг 2. Установка в ИИ-клиенты
На хосте запустите:
- **`INSTALL_ALL.bat`** — автоматически подключит сервер ко всем трем клиентам (**Antigravity**, **OpenCode**, **Codex**) сразу!
Или по отдельности:
- `INSTALL_ANTIGRAVITY.bat` — для Google Antigravity.
- `INSTALL_OPENCODE.bat` — для OpenCode.
- `INSTALL_CODEX.bat` — для Codex.

Проверить доступность виртуалки можно в 1 клик:
- **`TEST_CONNECTION.bat`**

---

## 🛠️ Содержимое Host Part
- `host_config.json` — IP, порт (37075) и токен (создаётся из `host_config.example.json`, не коммитится).
- `INSTALL_ALL.bat` — универсальный инсталлятор для всех сред.
- `INSTALL_ANTIGRAVITY.bat` — инсталлятор для Antigravity.
- `INSTALL_OPENCODE.bat` — инсталлятор для OpenCode.
- `INSTALL_CODEX.bat` — инсталлятор для Codex.
- `SET_IP_AND_TOKEN.bat` — утилита быстрой смены IP/токена.
- `TEST_CONNECTION.bat` — проверка здоровья агента на виртуалке (`/healthz`).
- `antigravity_schemas/` — 103 готовых JSON-схем инструментов для мгновенной интеграции.
- `vm_agent_bridge.py` — stdio мост для клиентов, не поддерживающих прямое HTTP-подключение.
- `port-forward.md` — подробное руководство по сетевым настройкам.

---

## 🔑 Доступные инструменты (103 инструментов)
- **Декомпиляция в C# псевдокод**:
  - `decompile_dotnet` — dnSpy.Console декомпиляция .NET сборок в читаемый C# код.
  - `go_symbols` — GoReSym восстановление символов, структур и путей из Go бинарников.
  - `rz_info` / `rizin` — нативное дизассемблирование, секции, метаданные.
- **Распаковка и дамп из памяти**:
  - `scan_memory_hollows` — PE-sieve и HollowsHunter (детект инжектов, хуков и Process Hollowing с авто-дампом).
  - `Scylla` — восстановление таблицы импорта (IAT).
- **Статический анализ**:
  - `die_scan` — Detect It Easy (компилятор, пакер, обфускатор, энтропия секций).
  - `capa_scan` — эвристический анализ возможностей от Mandiant (1071 правило).
  - `pe_info`, `pe_strings`, `pe_search`, `pe_disasm`, `pe_entropy`, `pe_hexdump`.
- **Динамическая отладка (x64dbg + ScyllaHide)**:
  - `dbg_launch`, `dbg_attach`, `dbg_hide_debugger` (анти-анти-отладка).
  - `dbg_set_breakpoint`, `dbg_run`, `dbg_step`, `dbg_pause`, `dbg_detach`.
  - `dbg_read_memory`, `dbg_write_memory`, `dbg_dump_module`, `dbg_registers`, `dbg_callstack`.
  - `dbg_search_pattern`, `dbg_search_string`, `dbg_patch`, `dbg_command`, `dbg_api`.
- **Полное управление ОС и файлами**:
  - `sys_exec`, `sys_powershell`, `sys_processes`, `sys_kill`, `sys_info`.
  - `fs_read_bytes`, `fs_write_bytes`, `fs_read_text`, `fs_write_text`, `fs_list`, `fs_zip`, `fs_unzip`.
- **Интерактивный GUI**:
  - `screen_capture`, `screen_pixel`, `input_click`, `input_type`, `input_key`, `win_list`, `win_focus`.
