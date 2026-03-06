use serde_json::Value;
use std::path::PathBuf;
use std::sync::Arc;
#[cfg(target_os = "windows")]
#[allow(unused_imports)]
use std::os::windows::process::CommandExt;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;

pub struct BridgeStateInner {
    pub stdin: Option<ChildStdin>,
    pub reader: Option<BufReader<ChildStdout>>,
    pub child: Option<Child>,
    pub child_pid: Option<u32>,
    pub stream_active: bool,
    pub bundled_java_home: Option<PathBuf>,
    pub init_error: Option<String>,
    pub stderr_buf: Arc<std::sync::Mutex<String>>,
}

pub type BridgeState = Arc<Mutex<BridgeStateInner>>;

const HANDSHAKE_TIMEOUT_SECS: u64 = 30;

fn kill_pid(pid: u32) {
    #[cfg(unix)]
    {
        let _ = std::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .status();
    }
    #[cfg(windows)]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/PID"])
            .arg(pid.to_string())
            .status();
    }
}

fn read_stderr_snapshot(buf: &Arc<std::sync::Mutex<String>>) -> String {
    buf.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

fn make_error_with_stderr(base_msg: &str, stderr_buf: &Arc<std::sync::Mutex<String>>) -> String {
    let stderr = read_stderr_snapshot(stderr_buf);
    if stderr.trim().is_empty() {
        base_msg.to_string()
    } else {
        let tail: String = stderr.lines().rev().take(30).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
        format!("{}\n\n--- Python stderr ---\n{}", base_msg, tail)
    }
}

fn find_bundled_bridge_exe() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let entries = std::fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        #[cfg(target_os = "windows")]
        if name_str.starts_with("mph-agent-bridge") && name_str.ends_with(".exe") {
            return Some(entry.path());
        }
        #[cfg(not(target_os = "windows"))]
        if name_str.starts_with("mph-agent-bridge") {
            return Some(entry.path());
        }
    }
    None
}

fn find_project_root() -> Option<PathBuf> {
    if let Ok(mut dir) = std::env::current_dir() {
        for _ in 0..10 {
            if dir.join("pyproject.toml").exists() {
                return Some(dir);
            }
            if !dir.pop() {
                break;
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(mut dir) = exe.parent().map(|p| p.to_path_buf()) {
            for _ in 0..10 {
                if dir.join("pyproject.toml").exists() {
                    return Some(dir);
                }
                if !dir.pop() {
                    break;
                }
            }
        }
    }
    None
}

fn find_python_cmd(root: &PathBuf) -> (String, Vec<String>) {
    let cli_path = root.join("cli.py");
    let cli_str = cli_path.to_string_lossy().to_string();

    #[cfg(target_os = "windows")]
    let venv_python = root.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(target_os = "windows"))]
    let venv_python = root.join(".venv").join("bin").join("python3");

    if venv_python.exists() {
        return (
            venv_python.to_string_lossy().to_string(),
            vec![cli_str, "tui-bridge".to_string()],
        );
    }

    #[cfg(target_os = "windows")]
    {
        (
            "py".to_string(),
            vec!["-3".to_string(), cli_str, "tui-bridge".to_string()],
        )
    }
    #[cfg(not(target_os = "windows"))]
    {
        (
            "python3".to_string(),
            vec![cli_str, "tui-bridge".to_string()],
        )
    }
}

pub fn bundled_java_home_from_app(app: &tauri::App) -> Option<PathBuf> {
    let res_dir = app.path().resource_dir().ok()?;
    let java_home = res_dir.join("runtime").join("java");
    #[cfg(target_os = "windows")]
    let has_java = java_home.join("bin").join("java.exe").exists();
    #[cfg(not(target_os = "windows"))]
    let has_java = java_home.join("bin").join("java").exists();
    if has_java {
        Some(java_home)
    } else {
        None
    }
}

pub struct BridgeHandles {
    pub stdin: ChildStdin,
    pub reader: BufReader<ChildStdout>,
    pub child: Child,
    pub pid: u32,
    pub stderr_buf: Arc<std::sync::Mutex<String>>,
}

fn spawn_stderr_reader(
    stderr: tokio::process::ChildStderr,
    buf: Arc<std::sync::Mutex<String>>,
) {
    tokio::spawn(async move {
        let mut reader = BufReader::new(stderr);
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line).await {
                Ok(0) => break,
                Ok(_) => {
                    eprint!("[bridge-stderr] {}", line);
                    if let Ok(mut b) = buf.lock() {
                        b.push_str(&line);
                        const MAX_STDERR: usize = 64 * 1024;
                        if b.len() > MAX_STDERR {
                            let cut = b.len() - MAX_STDERR / 2;
                            *b = b[cut..].to_string();
                        }
                    }
                }
                Err(_) => break,
            }
        }
    });
}

pub async fn init_bridge(bundled_java_home: Option<PathBuf>) -> Result<BridgeHandles, String> {
    let stderr_buf: Arc<std::sync::Mutex<String>> = Arc::new(std::sync::Mutex::new(String::new()));

    let mut child = spawn_bridge_child(&bundled_java_home).await?;

    let pid = child.id().unwrap_or(0);
    let stdin = child.stdin.take().ok_or("无法获取子进程 stdin")?;
    let stdout = child.stdout.take().ok_or("无法获取子进程 stdout")?;
    let stderr = child.stderr.take();

    if let Some(se) = stderr {
        spawn_stderr_reader(se, stderr_buf.clone());
    }

    let mut reader = BufReader::new(stdout);

    match tokio::time::timeout(
        std::time::Duration::from_secs(HANDSHAKE_TIMEOUT_SECS),
        wait_for_handshake(&mut reader),
    )
    .await
    {
        Ok(Ok(())) => {}
        Ok(Err(e)) => {
            let _ = child.kill().await;
            return Err(make_error_with_stderr(
                &format!("Bridge 握手失败: {}", e),
                &stderr_buf,
            ));
        }
        Err(_) => {
            let _ = child.kill().await;
            return Err(make_error_with_stderr(
                &format!(
                    "Bridge 握手超时 ({}s)：Python 进程未在规定时间内发送就绪信号",
                    HANDSHAKE_TIMEOUT_SECS
                ),
                &stderr_buf,
            ));
        }
    }

    Ok(BridgeHandles {
        stdin,
        reader,
        child,
        pid,
        stderr_buf,
    })
}

async fn wait_for_handshake(reader: &mut BufReader<ChildStdout>) -> Result<(), String> {
    let mut line = String::new();
    let bytes = reader
        .read_line(&mut line)
        .await
        .map_err(|e| format!("读取握手信号失败: {}", e))?;

    if bytes == 0 {
        return Err("Python 进程在发送握手信号前退出（stdout EOF）".to_string());
    }

    let trimmed = line.trim();
    let parsed: Value =
        serde_json::from_str(trimmed).map_err(|e| format!("握手信号 JSON 解析失败: {} (内容: {})", e, trimmed))?;

    if parsed.get("_ready").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(format!("收到非握手信号: {}", trimmed))
    }
}

async fn spawn_bridge_child(bundled_java_home: &Option<PathBuf>) -> Result<Child, String> {
    // 开发模式：找到 pyproject.toml 时优先用 Python 脚本
    if let Some(root) = find_project_root() {
        let (cmd, args) = find_python_cmd(&root);

        let mut builder = Command::new(&cmd);
        builder
            .args(&args)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .current_dir(&root)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUNBUFFERED", "1");

        if let Some(ref jh) = bundled_java_home {
            builder.env("JAVA_HOME", jh);
            builder.env("MPH_AGENT_USE_BUNDLED_JAVA", "1");
        }

        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            builder.creation_flags(CREATE_NO_WINDOW);
        }

        let child = builder.spawn().map_err(|e| {
            format!(
                "启动 Python bridge 失败 ({} {}): {}",
                cmd,
                args.join(" "),
                e
            )
        })?;

        return Ok(child);
    }

    // 打包模式：使用安装包内的 bridge 可执行文件
    if let Some(bridge_exe) = find_bundled_bridge_exe() {
        let mut builder = Command::new(&bridge_exe);
        builder
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        if let Some(ref d) = bridge_exe.parent() {
            builder.current_dir(d);
        }
        if let Some(ref jh) = bundled_java_home {
            builder.env("JAVA_HOME", jh);
            builder.env("MPH_AGENT_USE_BUNDLED_JAVA", "1");
        }
        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            builder.creation_flags(CREATE_NO_WINDOW);
        }
        let child = builder.spawn().map_err(|e| {
            format!(
                "启动打包 bridge 失败 ({}): {}",
                bridge_exe.display(),
                e
            )
        })?;
        return Ok(child);
    }

    Err(
        "找不到项目根目录 (pyproject.toml) 且无打包 bridge 可执行文件。安装包需包含 bridge 可执行文件；从源码运行需在项目根目录。"
            .to_string(),
    )
}

async fn restart_bridge(state: &BridgeState) {
    let java_home = {
        let guard = state.lock().await;
        guard.bundled_java_home.clone()
    };
    match init_bridge(java_home).await {
        Ok(handles) => {
            let mut g = state.lock().await;
            g.stdin = Some(handles.stdin);
            g.reader = Some(handles.reader);
            g.child = Some(handles.child);
            g.child_pid = Some(handles.pid);
            g.stderr_buf = handles.stderr_buf;
            g.init_error = None;
        }
        Err(e) => {
            let mut g = state.lock().await;
            g.init_error = Some(e);
        }
    }
}

#[tauri::command]
pub async fn bridge_send(
    state: tauri::State<'_, BridgeState>,
    cmd: String,
    payload: Value,
) -> Result<Value, String> {
    let (mut stdin, mut reader, stderr_buf) = {
        let mut guard = state.inner().lock().await;
        let s = guard.stdin.take().ok_or("Bridge 未初始化")?;
        let r = guard.reader.take().ok_or("Bridge 未初始化")?;
        let se = guard.stderr_buf.clone();
        (s, r, se)
    };

    let mut req = match payload.as_object() {
        Some(obj) => obj.clone(),
        None => serde_json::Map::new(),
    };
    req.insert("cmd".into(), Value::String(cmd));

    let line = serde_json::to_string(&Value::Object(req)).map_err(|e| e.to_string())?;
    let line_with_newline = format!("{}\n", line);

    if let Err(e) = stdin.write_all(line_with_newline.as_bytes()).await {
        let err = make_error_with_stderr(&format!("写入 bridge stdin 失败: {}", e), &stderr_buf);
        restart_bridge(state.inner()).await;
        return Err(err);
    }
    if let Err(e) = stdin.flush().await {
        let err = make_error_with_stderr(&format!("flush bridge stdin 失败: {}", e), &stderr_buf);
        restart_bridge(state.inner()).await;
        return Err(err);
    }

    let mut resp_line = String::new();
    let bytes = match reader.read_line(&mut resp_line).await {
        Ok(b) => b,
        Err(e) => {
            let err =
                make_error_with_stderr(&format!("读取 bridge stdout 失败: {}", e), &stderr_buf);
            restart_bridge(state.inner()).await;
            return Err(err);
        }
    };

    if bytes == 0 {
        let err = make_error_with_stderr("Bridge 子进程已退出（EOF）", &stderr_buf);
        restart_bridge(state.inner()).await;
        return Err(err);
    }

    let trimmed = resp_line.trim();
    if trimmed.is_empty() {
        let err = make_error_with_stderr("Bridge 返回为空", &stderr_buf);
        restart_bridge(state.inner()).await;
        return Err(err);
    }

    {
        let mut guard = state.inner().lock().await;
        guard.stdin = Some(stdin);
        guard.reader = Some(reader);
    }

    serde_json::from_str(trimmed).map_err(|e| format!("JSON 解析失败: {} (内容: {})", e, trimmed))
}

#[tauri::command]
pub async fn bridge_send_stream(
    app: AppHandle,
    state: tauri::State<'_, BridgeState>,
    cmd: String,
    payload: Value,
) -> Result<Value, String> {
    let (mut stdin, mut reader, stderr_buf, pid) = {
        let mut guard = state.inner().lock().await;
        let s = guard.stdin.take().ok_or("Bridge 未初始化")?;
        let r = guard.reader.take().ok_or("Bridge 未初始化")?;
        let se = guard.stderr_buf.clone();
        let p = guard.child_pid;
        guard.stream_active = true;
        (s, r, se, p)
    };

    if let Some(p) = pid {
        let mut guard = state.inner().lock().await;
        guard.child_pid = Some(p);
    }

    let mut req = match payload.as_object() {
        Some(obj) => obj.clone(),
        None => serde_json::Map::new(),
    };
    req.insert("cmd".into(), Value::String(cmd));

    let line = serde_json::to_string(&Value::Object(req)).map_err(|e| e.to_string())?;
    let line_with_newline = format!("{}\n", line);

    if let Err(e) = stdin.write_all(line_with_newline.as_bytes()).await {
        let err = make_error_with_stderr(
            &format!("写入 bridge stdin 失败: {}", e),
            &stderr_buf,
        );
        let mut guard = state.inner().lock().await;
        guard.stream_active = false;
        drop(guard);
        restart_bridge(state.inner()).await;
        return Err(err);
    }
    if let Err(e) = stdin.flush().await {
        let err = make_error_with_stderr(
            &format!("flush bridge stdin 失败: {}", e),
            &stderr_buf,
        );
        let mut guard = state.inner().lock().await;
        guard.stream_active = false;
        drop(guard);
        restart_bridge(state.inner()).await;
        return Err(err);
    }

    let result = loop {
        let mut resp_line = String::new();
        let bytes = match reader.read_line(&mut resp_line).await {
            Ok(b) => b,
            Err(e) => {
                break Err(make_error_with_stderr(
                    &format!("读取 bridge stdout 失败: {}", e),
                    &stderr_buf,
                ));
            }
        };

        if bytes == 0 {
            break Err(make_error_with_stderr(
                "Bridge 子进程已退出，未收到完整响应",
                &stderr_buf,
            ));
        }

        let trimmed = resp_line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let parsed: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                break Err(format!("JSON 解析失败: {} (内容: {})", e, trimmed));
            }
        };

        if parsed.get("_event").and_then(|v| v.as_bool()) == Some(true) {
            let _ = app.emit("bridge-event", &parsed);
        } else {
            break Ok(parsed);
        }
    };

    {
        let mut guard = state.inner().lock().await;
        guard.stream_active = false;
        if result.is_ok() {
            guard.stdin = Some(stdin);
            guard.reader = Some(reader);
        } else {
            guard.stdin.take();
            guard.reader.take();
            guard.child.take();
            guard.child_pid.take();
            drop(guard);
            restart_bridge(state.inner()).await;
        }
    }

    result
}

#[tauri::command]
pub async fn bridge_abort(state: tauri::State<'_, BridgeState>) -> Result<(), String> {
    let pid = {
        let mut guard = state.inner().lock().await;
        let p = guard.child_pid.take();
        guard.stdin.take();
        guard.reader.take();
        if let Some(mut child) = guard.child.take() {
            let _ = child.kill().await;
        }
        guard.stream_active = false;
        p
    };
    if let Some(p) = pid {
        kill_pid(p);
    }
    restart_bridge(state.inner()).await;
    let guard = state.inner().lock().await;
    if let Some(ref e) = guard.init_error {
        Err(e.clone())
    } else {
        Ok(())
    }
}

#[tauri::command]
pub async fn bridge_init_status(
    state: tauri::State<'_, BridgeState>,
) -> Result<serde_json::Value, String> {
    let guard = state.inner().lock().await;
    let ready = guard.stdin.is_some() && guard.reader.is_some();
    let error = guard.init_error.clone();
    drop(guard);
    Ok(serde_json::json!({ "ready": ready, "error": error }))
}

#[tauri::command]
pub async fn open_path(path: String) -> Result<(), String> {
    let path = path.trim();
    if path.is_empty() {
        return Err("路径为空".to_string());
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn open_in_folder(path: String) -> Result<(), String> {
    let path = path.trim();
    if path.is_empty() {
        return Err("路径为空".to_string());
    }
    let path_buf = std::path::PathBuf::from(path);
    if !path_buf.exists() {
        return Err("文件或目录不存在".to_string());
    }
    let dir = if path_buf.is_dir() {
        path_buf
    } else {
        path_buf
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or(path_buf)
    };
    let abs = dir.canonicalize().map_err(|e| e.to_string())?;
    let dir_str = abs.to_string_lossy().to_string();

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(&dir_str)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&dir_str)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(&dir_str)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}
