# 桌面端 Bridge 报错代码位置（排查用）

问题定位在 **desktop/src-tauri/src** 的桥接相关代码。以下为可能向用户输出「Bridge process closed unexpectedly」及相关错误的代码块，便于逐块排查。

---

## 1. 用户看到的报错来源

### 1.1 「Bridge 子进程已退出，未收到完整响应...」（流式请求时子进程 stdout 关闭）

**文件**: `bridge.rs`  
**行号**: **307-309**（常量 `ERR_BRIDGE_CLOSED`）、**298-311**（loop 内）

```rust
if bytes == 0 {
    break Err(ERR_BRIDGE_CLOSED.to_string());
}
```

**含义**: `bridge_send_stream` 从子进程 stdout 读一行时得到 **0 字节（EOF）**，说明子进程已退出且未再写数据。

**加固后行为**: 返回错误后会自动尝试 `init_bridge` 重启子进程并写回 state；若重启成功，下一次请求可继续使用。错误文案会引导用户设置 `MPH_AGENT_BRIDGE_DEBUG=1` 并查看 `%TEMP%\mph-agent-bridge-debug.log`。

---

### 1.2 「Bridge 返回为空...」（非流式请求时读到空）

**文件**: `bridge.rs`  
**行号**: 常量 `ERR_EMPTY_RESPONSE`，**bridge_send** 内 `bytes == 0` / `trimmed.is_empty()` 分支

**含义**: 非流式命令（`bridge_send`）读到的第一行为空或 EOF。

**加固后行为**: 会丢弃已死的 child、尝试 `init_bridge` 重启并写回 state，再返回带调试提示的 `ERR_EMPTY_RESPONSE`。

---

### 1.3 「Python bridge not initialized」

**文件**: `bridge.rs`  
**行号**: **266-268**（`bridge_send_stream`）、**220**（`bridge_send`）

```rust
guard.child.take().ok_or("Python bridge not initialized")?
// 或
let child = guard.child.as_mut().ok_or("Python bridge not initialized")?;
```

**含义**: 启动时 `init_bridge` 失败或未执行成功，`state.child` 为 `None`。用户在前端调用 `bridge_send` / `bridge_send_stream` 时会看到此错误。

**关联**: `lib.rs` 第 36-45 行 — 若 `init_bridge` 失败，仅 `eprintln!` 警告，不会把 child 写入 state，后续所有 bridge 调用都会报 "not initialized"。

---

## 2. 子进程启动与重启（影响「是否有 bridge」与「环境」）

### 2.1 init_bridge：启动失败时的错误信息

**文件**: `bridge.rs`  
**行号**: **160-163**（打包 exe）、**196-203**（Python 开发）、**169**、**206-207**

```rust
// 打包 bridge 启动失败
let child = builder.spawn().map_err(|e| {
    format!("Failed to start bundled bridge ({}): {}", bridge_exe.display(), e)
})?;

// 开发环境 Python 启动失败
let child = builder.spawn().map_err(|e| {
    format!(
        "Failed to start Python bridge ({} {}): {}",
        cmd, args.join(" "), e
    )
})?;
// ...
if child.stdin.is_none() || child.stdout.is_none() {
    return Err("Failed to capture stdin/stdout".to_string());
}
```

以及**找不到项目根**时（约 169 行）：

```rust
let root = find_project_root().ok_or("Cannot find project root (pyproject.toml). 安装包需包含 bridge 可执行文件；从源码运行需在项目根目录。")?;
```

**排查方向**:
- 开发时：是否从项目根启动、是否有 `pyproject.toml`、`find_project_root()` 是否找对目录。
- 打包时：`find_bundled_bridge_exe()` 是否找到 exe、`current_dir` 是否为 exe 所在目录。
- Windows：`CREATE_NO_WINDOW`、stdin/stdout 是否被正确 pipe。

---

### 2.2 应用启动时 init_bridge 失败（仅打日志，不抛给前端）

**文件**: `lib.rs`  
**行号**: **33-46**

```rust
.setup(|app| {
    let state = app.state::<BridgeState>().inner().clone();
    let java_home = bundled_java_home_from_app(app);
    let rt = tokio::runtime::Runtime::new().expect("create tokio runtime");
    match rt.block_on(init_bridge(java_home.clone())) {
        Ok(child) => {
            let mut guard = state.as_ref().blocking_lock();
            guard.bundled_java_home = java_home;
            guard.child = Some(child);
        }
        Err(e) => {
            eprintln!("Warning: Failed to initialize Python bridge: {}", e);
        }
    }
    Ok(())
})
```

**含义**: 若这里 `Err(e)`，用户不会在 UI 看到该错误，但之后任意 bridge 调用都会得到「Python bridge not initialized」。排查时看终端/日志里的 `Warning: Failed to initialize Python bridge: ...`。

---

### 2.3 bridge_abort 后重启失败

**文件**: `bridge.rs`  
**行号**: **338-361**

```rust
#[tauri::command]
pub async fn bridge_abort(state: tauri::State<'_, BridgeState>) -> Result<(), String> {
    // ... kill 当前 child ...
    match init_bridge(java_home).await {
        Ok(child) => { guard.child = Some(child); Ok(()) }
        Err(e) => Err(e),   // 错误会返回给前端
    }
}
```

**含义**: 用户点「停止」后，若重新 `init_bridge` 失败，前端会收到 `Err(e)`（与 2.1 中同样的错误文案）。

---

## 3. 流式请求中的其它错误（同一调用链）

**文件**: `bridge.rs`，`bridge_send_stream` 内

| 行号   | 错误文案 / 含义 |
|--------|------------------|
| 284-285 | `Stdin not available` — child 的 stdin 为 None（异常状态） |
| 291-294 | `Write to bridge failed: {}` — 写 stdin 失败 |
| 295-296 | `Flush bridge failed: {}` — flush stdin 失败 |
| 297    | `Stdout not available` — child 的 stdout 为 None |
| 303-304 | `Read from bridge failed: {}` — 读 stdout 时 I/O 错误（非 EOF） |
| 316    | `Invalid JSON: {}` — 收到非 _event 的一行但不是合法 JSON |

这些都会作为 `bridge_send_stream` 的 `Err(String)` 返回给前端；只有 **bytes == 0** 时才是「Bridge process closed unexpectedly」。

---

## 4. 建议的排查顺序

1. **确认是否曾成功启动 bridge**  
   看启动时是否有 `Warning: Failed to initialize Python bridge`（`lib.rs` 43 行）；若有，重点查 `init_bridge`（2.1）和 `find_project_root` / `find_bundled_bridge_exe`。

2. **复现「Bridge process closed unexpectedly」**  
   确认是调用 `bridge_send_stream`（run）时出现，则问题在 1.1：子进程在 Rust 读到最终一行之前就退出了。可配合 Python 端 `MPH_AGENT_BRIDGE_DEBUG=1` 与 `%TEMP%\mph-agent-bridge-debug.log` 看子进程是否写出了最终 JSON、是否异常退出。

3. **对比环境**  
   对比 Tauri 启动子进程时的 `current_dir`、环境变量（如 `HTTP_PROXY`）、以及是否使用打包 exe vs 开发用 `python cli.py tui-bridge`，与「单独管道测试能正常返回」的环境是否一致。

4. **管道与缓冲**  
   若日志显示 Python 已写出最终行且正常退出，但 Rust 仍报 1.1，可怀疑 Windows 下管道/缓冲行为，在 Python 端对 stdout 做 `flush` 并确认无重定向或缓冲设置问题。

以上所有会向用户输出报错的代码块均在 **desktop/src-tauri/src** 的 `bridge.rs` 与 `lib.rs` 中，按上述行号即可定位到具体代码块进行修改或加日志。
