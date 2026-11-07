import type { ReactNode, MouseEvent } from "react";
import type { DialogType } from "../../lib/types";

interface Props {
  onClose: () => void;
  children: ReactNode;
  dialogType?: DialogType;
}

function buildDialogClassName(base: string, dialogType?: DialogType): string {
  return dialogType ? `${base} ${base}--${dialogType}` : base;
}

export function DialogOverlay({ onClose, children, dialogType }: Props) {
  const handleBackdrop = (e: MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div
      className={buildDialogClassName("dialog-overlay", dialogType)}
      onClick={handleBackdrop}
      role="presentation"
    >
      <div
        className={buildDialogClassName("dialog-box", dialogType)}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
