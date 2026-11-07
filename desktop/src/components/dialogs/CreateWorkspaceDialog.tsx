import { useCallback, useEffect, useState } from "react";
import { open as openFolderDialog } from "@tauri-apps/plugin-dialog";
import { DialogOverlay } from "./DialogOverlay";
import { Icon } from "../Icon";

interface CreateWorkspaceDialogProps {
  open: boolean;
  onCancel: () => void;
  onCreate: (payload: { name: string; folderPath: string }) => void;
}

function folderNameFromPath(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function CreateWorkspaceDialog({
  open: visible,
  onCancel,
  onCreate,
}: CreateWorkspaceDialogProps) {
  const [name, setName] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [picking, setPicking] = useState(false);
  const [pickError, setPickError] = useState("");

  useEffect(() => {
    if (!visible) return;
    setName("");
    setFolderPath("");
    setNameTouched(false);
    setPickError("");
    setPicking(false);
  }, [visible]);

  const pickFolder = useCallback(async () => {
    setPickError("");
    setPicking(true);
    try {
      const selected = await openFolderDialog({
        directory: true,
        multiple: false,
        title: "选择工作空间目录",
      });
      if (selected == null) return;
      const path = String(selected);
      setFolderPath(path);
      if (!nameTouched || !name.trim()) {
        setName(folderNameFromPath(path));
      }
    } catch (error) {
      setPickError(`无法打开目录选择器：${String(error)}`);
    } finally {
      setPicking(false);
    }
  }, [name, nameTouched]);

  if (!visible) return null;

  const canCreate = Boolean(folderPath.trim());

  return (
    <DialogOverlay onClose={onCancel}>
      <div className="create-workspace-dialog">
        <div className="create-workspace-dialog__header">
          <h2 className="create-workspace-dialog__title">新建工作空间</h2>
          <button
            type="button"
            className="create-workspace-dialog__close"
            onClick={onCancel}
            title="关闭"
            aria-label="关闭"
          >
            <Icon name="close-circle" size={18} />
          </button>
        </div>

        <div className="create-workspace-dialog__body">
          <label className="create-workspace-name">
            <span className="create-workspace-name__icon" aria-hidden="true">
              <Icon name="folder-2" size={16} />
            </span>
            <input
              type="text"
              className="create-workspace-name__input"
              placeholder="工作空间名称"
              value={name}
              onChange={(e) => {
                setNameTouched(true);
                setName(e.target.value);
              }}
              autoFocus
            />
          </label>

          <div className="create-workspace-source">
            <div className="create-workspace-source__label">本地目录</div>
            <div className="create-workspace-source__box">
              <div className="create-workspace-source__meta">
                <span className="create-workspace-source__hint">
                  {folderPath
                    ? folderPath
                    : "添加本机上的一个文件夹"}
                </span>
              </div>
              <button
                type="button"
                className="create-workspace-source__add"
                disabled={picking}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void pickFolder();
                }}
              >
                <Icon name="folder-add" size={15} />
                {picking ? "选择中…" : "添加"}
              </button>
            </div>
            {pickError ? (
              <p className="create-workspace-source__error">{pickError}</p>
            ) : null}
          </div>
        </div>

        <div className="create-workspace-dialog__footer">
          <button
            type="button"
            className="dialog-btn create-workspace-cancel"
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            className="dialog-btn primary create-workspace-submit"
            disabled={!canCreate}
            onClick={() => {
              if (!canCreate) return;
              onCreate({
                name: name.trim() || folderNameFromPath(folderPath),
                folderPath: folderPath.trim(),
              });
            }}
          >
            创建工作空间
          </button>
        </div>
      </div>
    </DialogOverlay>
  );
}
