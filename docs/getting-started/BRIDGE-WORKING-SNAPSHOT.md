# Bridge 能跑通时的代码快照 (f183ac2 – desktop-v0.1.1)

提交 **f183ac2**（`release: jpype 延迟导入与 bridge 构建配置 (desktop-v0.1.1)`）是桌面端/Bridge 相关、最近一次“能跑通”的参考版本。  
下面是对比当前代码的差异摘要，以及如何按文件回退到该版本。

---

## 1. 当时能跑通的形态（摘要）

### 1.1 Rust：`desktop/src-tauri/src/lib.rs`

- **BridgeStateInner** 只有 3 个字段：`child`, `stream_pid`, `bundled_java_home`（**没有** `init_error`）。
- **invoke_handler** 只注册：`bridge_send`, `bridge_send_stream`, `bridge_abort`, `open_path`, `open_in_folder`, `apply_window_icon`（**没有** `bridge_init_status`）。
- **init_bridge 失败时**：仅 `eprintln!("Warning: Failed to initialize Python bridge: {}", e)`，**不**把错误写入 state。

### 1.2 Rust：`desktop/src-tauri/src/bridge.rs`

- **BridgeStateInner** 无 `init_error`。
- **init_bridge**：
  - 无 `MPH_AGENT_BRIDGE_DEBUG` 判断；
  - 无 `PYTHONUNBUFFERED`；
  - 子进程 **stderr 始终** `Stdio::null()`。
- **bridge_send**：读到空/EOF 时直接 `return Err("Empty response from bridge".to_string())`，**不**做自动重启、不写 `init_error`。
- **bridge_send_stream**：`bytes == 0` 时 `break Err("Bridge process closed unexpectedly".to_string())`，**不**自动重启。
- **bridge_abort** 成功后**不**清 `init_error`（因为当时没有该字段）。
- **没有** `bridge_init_status` 命令。

### 1.3 Python：`agent/run/tui_bridge.py`

- **导入**：所有 import 在文件顶部**直接执行**，没有 `try/except` 也没有 `_early_log`。
- **无** `_bridge_debug()`、`_debug_log()`、`_early_log_path()`、excepthook、调试日志文件。
- **run 命令**：仅一层 `try/except Exception`，成功则 `_reply(ok, msg)`，异常则 `_emit_event` + `_reply(False, str(e))`；**没有** `replied` 标志和 `finally` 保底回复。
- **main**：没有调试相关逻辑；循环里 `json.loads` 失败时 `_reply(False, ...)` 并 `continue`；**没有** `try/except BaseException` 包裹 `_handle(req)`，直接 `_handle(req)`。

### 1.4 前端：`desktop/src/App.tsx`

- **没有** `bridgeStatus`、`bridge_init_status` 调用、Bridge 未就绪的顶部提示条。
- 只有原有的 `useEffect`（图标、Esc 关闭对话框等）。

---

## 2. 当前相对 f183ac2 的主要改动（可能影响行为）

| 位置 | 当前相对 f183ac2 的改动 |
|------|------------------------|
| **lib.rs** | 增加 `init_error`；init 失败时写入 `guard.init_error`；注册 `bridge_init_status`。 |
| **bridge.rs** | 增加 `init_error`、`ERR_*` 常量、`MPH_AGENT_BRIDGE_DEBUG`、`PYTHONUNBUFFERED`、空/EOF 时自动重启并写 `init_error`、`bridge_init_status`。 |
| **tui_bridge.py** | 启动时 `_early_log`、import 包在 `try/except` 里并写日志、`_bridge_debug`/`_debug_log`、run 的 `replied`+`finally`、main 里 `BaseException` 捕获并 `_reply` 后 `raise`。 |
| **App.tsx** | 调用 `bridge_init_status` 并显示 “Bridge 未就绪” 的红色条。 |

这些改动大多是**增强**（错误展示、调试、自动重启），**一般不会**单独导致“init_bridge 一直不就绪”。若当时在同一环境（同一项目根、同一启动方式）能跑通，现在不能，多半是**环境/启动方式**变化；若你希望排除“最近代码”的影响，可以临时回退到 f183ac2 做对比。

---

## 3. 如何回退到 f183ac2 的对应文件（仅作对比/排查）

在项目根执行（PowerShell）：

```powershell
# 仅恢复 Bridge/桌面 相关文件到 f183ac2（其它文件不动）
git checkout f183ac2 -- desktop/src-tauri/src/lib.rs desktop/src-tauri/src/bridge.rs agent/run/tui_bridge.py desktop/src/App.tsx
```

注意：

- 恢复后 **lib.rs / bridge.rs** 会少掉 `init_error` 和 `bridge_init_status`，前端 **App.tsx** 会少掉 Bridge 未就绪提示条；**Rust 编译会报错**，因为当前 `BridgeStateInner` 在别处可能已引用 `init_error`，需要一并改回或先只恢复 Python/前端试运行。
- 更稳妥的方式是：**只恢复 `agent/run/tui_bridge.py`**，看 Bridge 子进程是否能正常启动、能跑通；若仍不就绪，则问题更可能在 Rust 或环境，而不是 Python 这段。

仅恢复 Python bridge（推荐先试）：

```powershell
git checkout f183ac2 -- agent/run/tui_bridge.py
```

若你要**完整回到 f183ac2 的桌面/Bridge 行为**（包括不再要 init_error、bridge_init_status、未就绪提示条），需要同时恢复上述 4 个文件，并确保 `BridgeStateInner` 及相关类型与 f183ac2 一致（无 `init_error`、无 `bridge_init_status`）。

---

## 4. 参考：f183ac2 的 tui_bridge.py 入口与 run 分支

**main（入口）：**

```python
def main() -> None:
    if sys.stdin.isatty():
        sys.stderr.write("tui-bridge: 请通过管道或子进程调用，不要直接交互运行\n")
        sys.exit(1)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _reply(False, f"JSON 解析错误: {e}")
            continue
        _handle(req)
```

**run 分支：**

```python
if cmd == "run":
    event_bus = EventBus()
    event_bus.subscribe_all(_emit_event)
    try:
        ok, msg = do_run(...)
        _reply(ok, msg)
    except Exception as e:
        _emit_event(Event(type=EventType.ERROR, data={"message": str(e)}))
        _reply(False, str(e))
    return
```

以上即“能跑通时”的代码形态与和当前的差异摘要；需要逐文件完整 diff 时可使用：

```powershell
git diff f183ac2 -- desktop/src-tauri/src/bridge.rs
git diff f183ac2 -- agent/run/tui_bridge.py
# 等等
```
