fn main() {
    ensure_icon_ico();
    tauri_build::build()
}

/// 生成符合 RC / include_image 要求的 ICO，Windows 与 macOS 开发模式都需要。
fn ensure_icon_ico() {
    use std::path::Path;

    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR");
    let icon_path = Path::new(&manifest_dir).join("icons").join("icon.ico");
    if icon_path.exists() {
        return;
    }

    let rgba: Vec<u8> = (0..32 * 32 * 4)
        .map(|i| {
            if i % 4 == 3 {
                255
            } else {
                [0x25u8, 0x63, 0xeb][i % 4]
            }
        })
        .collect();

    let image = ico::IconImage::from_rgba_data(32, 32, rgba);
    let mut icon_dir = ico::IconDir::new(ico::ResourceType::Icon);
    icon_dir.add_entry(ico::IconDirEntry::encode(&image).expect("encode icon"));
    let file = std::fs::File::create(&icon_path).expect("create icon.ico");
    icon_dir.write(file).expect("write icon.ico");
}
