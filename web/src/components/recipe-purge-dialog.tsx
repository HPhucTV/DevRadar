"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

export function RecipePurgeDialog({
  open,
  recipeCode,
  title,
  description,
  inputLabel,
  cancelLabel,
  confirmLabel,
  busyLabel,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean;
  recipeCode: string;
  title: string;
  description: string;
  inputLabel: string;
  cancelLabel: string;
  confirmLabel: string;
  busyLabel: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: (confirmationCode: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [confirmation, setConfirmation] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  function close() {
    if (busy) return;
    setConfirmation("");
    onClose();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (confirmation === recipeCode && !busy) onConfirm(confirmation);
  }

  return <dialog
    aria-describedby="recipe-purge-description"
    aria-labelledby="recipe-purge-title"
    className="recipe-purge-dialog"
    onCancel={(event) => { event.preventDefault(); close(); }}
    onClose={() => setConfirmation("")}
    onKeyDown={(event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    }}
    ref={dialogRef}
  >
    <form onSubmit={submit}>
      <h2 id="recipe-purge-title">{title}</h2>
      <p id="recipe-purge-description">{description}</p>
      <label htmlFor="recipe-purge-confirmation">{inputLabel}<strong>{recipeCode}</strong></label>
      <input
        autoComplete="off"
        id="recipe-purge-confirmation"
        onChange={(event) => setConfirmation(event.target.value)}
        spellCheck={false}
        value={confirmation}
      />
      <div className="recipe-purge-actions">
        <button className="button-secondary" disabled={busy} onClick={close} type="button">{cancelLabel}</button>
        <button className="button-danger" disabled={busy || confirmation !== recipeCode} type="submit">{busy ? busyLabel : confirmLabel}</button>
      </div>
    </form>
  </dialog>;
}
