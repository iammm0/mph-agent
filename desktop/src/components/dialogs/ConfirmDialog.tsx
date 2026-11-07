import type { ReactNode } from "react";
import { DialogOverlay } from "./DialogOverlay";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确定",
  cancelLabel = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <DialogOverlay onClose={onCancel}>
      <div className="dialog-header" id="confirm-dialog-title">
        {title}
      </div>
      <div className="dialog-body confirm-dialog-body">
        <p className="confirm-dialog-message">{message}</p>
      </div>
      <div className="dialog-footer confirm-dialog-actions">
        <button type="button" className="dialog-btn secondary" onClick={onCancel}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={danger ? "dialog-btn danger" : "dialog-btn primary"}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
      </div>
    </DialogOverlay>
  );
}
