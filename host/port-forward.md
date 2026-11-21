# Проброс портов из виртуальной машины на хост (Port Forwarding)

Агент внутри ВМ по умолчанию слушает на порту **37075** (`0.0.0.0:37075`).

### 1. VMware Workstation / Player:
1. Откройте `Edit` -> `Virtual Network Editor`.
2. Выберите сеть `NAT` (обычно `VMnet8`) и нажмите кнопку `NAT Settings...`.
3. В разделе `Port Forwarding` нажмите `Add`:
   - **Host Port:** `37075`
   - **Type:** `TCP`
   - **Virtual machine IP address:** `<IP_виртуальной_машины>` (узнать в ВМ через `ipconfig`)
   - **Virtual machine port:** `37075`
   - **Description:** `AgentKit MCP`
4. Нажмите `OK`.

### 2. VirtualBox:
1. Откройте настройки ВМ -> `Network` -> `Adapter 1` (NAT).
2. Разверните `Advanced` и нажмите `Port Forwarding`.
3. Добавьте правило:
   - **Protocol:** `TCP`
   - **Host Port:** `37075`
   - **Guest Port:** `37075`
4. Нажмите `OK`.

### 3. Проверка подключения с хоста:
В PowerShell на хосте:
```powershell
curl.exe http://127.0.0.1:37075/healthz
```
Должен вернуть статус `{"status":"ok", ...}`.
