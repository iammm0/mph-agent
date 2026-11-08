mod bridge;

use bridge::{
    bridge_abort, bridge_ensure_ready, bridge_init_status, bridge_send, bridge_send_stream, bundled_java_home_from_app,
    init_bridge, open_in_folder, open_path, BridgeState, BridgeStateInner,
};
use std::path::Path;
use std::sync::Arc;
use tauri::{Emitter, Manager};
use tokio::sync::Mutex;

#[tauri::command]
fn apply_window_icon(window: tauri::WebviewWindow) {
    let icon = tauri::include_image!("icons/icon.ico");
    if let Err(e) = window.set_icon(icon) {
        eprintln!("Failed to set window icon: {}", e);
    }
}

/// 从启动参数中解析首个 `.mphb` 路径（双击关联文件冷启动）。
fn find_mphb_arg() -> Option<String> {
    for arg in std::env::args().skip(1) {
        let trimmed = arg.trim().trim_matches('"');
        if trimmed.is_empty() {
            continue;
        }
        let path = Path::new(trimmed);
        if path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.eq_ignore_ascii_case("mphb"))
            .unwrap_or(false)
        {
            return Some(trimmed.to_string());
        }
    }
    None
}

#[tauri::command]
fn cli_open_path() -> Option<String> {
    find_mphb_arg()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Arc::new(Mutex::new(BridgeStateInner {
            stdin: None,
            reader: None,
            child: None,
            child_pid: None,
            stream_active: false,
            init_in_progress: false,
            bundled_java_home: None,
            init_error: None,
            stderr_buf: Arc::new(std::sync::Mutex::new(String::new())),
        })))
        .invoke_handler(tauri::generate_handler![
            bridge_send,
            bridge_send_stream,
            bridge_abort,
            bridge_ensure_ready,
            bridge_init_status,
            open_path,
            open_in_folder,
            apply_window_icon,
            cli_open_path,
        ])
        .setup(|app| {
            let state = app.state::<BridgeState>().inner().clone();
            let java_home = bundled_java_home_from_app(app);
            if let Some(mphb) = find_mphb_arg() {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    // 等前端挂载后再发事件
                    tokio::time::sleep(std::time::Duration::from_millis(800)).await;
                    let _ = handle.emit("open-mphb", mphb);
                });
            }
            tauri::async_runtime::spawn(async move {
                {
                    let mut guard = state.lock().await;
                    guard.bundled_java_home = java_home.clone();
                    guard.init_in_progress = true;
                    guard.init_error = None;
                }
                match init_bridge(java_home.clone()).await {
                    Ok(handles) => {
                        let mut guard = state.lock().await;
                        guard.bundled_java_home = java_home;
                        guard.stdin = Some(handles.stdin);
                        guard.reader = Some(handles.reader);
                        guard.child = Some(handles.child);
                        guard.child_pid = Some(handles.pid);
                        guard.stderr_buf = handles.stderr_buf;
                        guard.init_error = None;
                        guard.init_in_progress = false;
                    }
                    Err(e) => {
                        eprintln!("Warning: Failed to initialize Python bridge: {}", e);
                        let mut guard = state.lock().await;
                        guard.bundled_java_home = java_home;
                        guard.init_error = Some(e);
                        guard.init_in_progress = false;
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
