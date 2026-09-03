use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct SidecarState(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            let parent_pid = std::process::id().to_string();
            let sidecar = app
                .shell()
                .sidecar("growth-mirror-service")?
                .args(["--parent-pid", &parent_pid]);
            let (mut events, child) = sidecar.spawn()?;
            *app.state::<SidecarState>().0.lock().expect("sidecar lock poisoned") =
                Some(child);

            tauri::async_runtime::spawn(async move {
                while events.recv().await.is_some() {
                    // Drain process events so the sidecar cannot block on output.
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Growth Mirror desktop application");

    application.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(child) = app_handle
                .state::<SidecarState>()
                .0
                .lock()
                .expect("sidecar lock poisoned")
                .take()
            {
                let _ = child.kill();
            }
        }
    });
}
