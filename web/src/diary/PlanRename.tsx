import { useEffect, useRef, useState } from 'react';

import { parsedPlanName, planNameHint, renameFailure } from '../plan/rename';
import { useRenamePlan } from '../plan/renameApi';
import { IconPencil } from '../ui/icons';

/** One plan's name, made editable — a finished plan as much as the active one, which is the
 *  point: the name is how a climber tells last spring's block from this one. */

/** ⚠️ `canRename` is FALSE for a demo principal and the PENCIL is then ABSENT, not disabled
 *  (issue #65) — the NAME still renders. ONE writable property, never a second field. */
export function PlanRename({
  planId,
  planName,
  canRename,
  idPrefix,
}: {
  planId: number;
  planName: string;
  canRename: boolean;
  idPrefix: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const rename = useRenamePlan();
  const fieldRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const editing = draft !== null;

  useEffect(() => {
    const opened = editing && !wasEditing.current;
    const closed = !editing && wasEditing.current;
    wasEditing.current = editing;
    if (opened) fieldRef.current?.focus();
    if (!closed) return;
    // ⚠️ Rescue focus ONLY when it is stranded on `<body>`, where React drops it after removing
    // the control just pressed — `SessionJournal`'s rule. Any other time it would be a theft.
    const active = document.activeElement;
    if (active === null || active === document.body) openerRef.current?.focus();
  }, [editing]);

  async function save(typed: string): Promise<void> {
    // ⚠️ Refused on the STRIPPED value but SENT raw: the server strips, and its reply is then the
    // only place the stored name exists. The Save control is absent here, the 422 behind it.
    if (parsedPlanName(typed) === null) return;
    try {
      await rename.mutateAsync({ planId, name: typed });
    } catch {
      // `rename.isError` says so below, with what was typed still in the field.
      return;
    }
    setDraft(null);
  }

  // ⚠️ The collapsed PENCIL is all that belongs beside the name; the field and its Save/Cancel
  // are a row of their own below, and the opener is what focus is rescued to when they go.
  const head = (
    <div className="ct-app__planhead">
      <h2>{planName}</h2>
      {canRename && draft === null ? (
        <button
          type="button"
          ref={openerRef}
          className="ct-app__button ct-app__button--icon ct-app__button--quiet"
          aria-label={`Rename ${planName}`}
          title={`Rename ${planName}`}
          onClick={() => {
            rename.reset();
            setDraft(planName);
          }}
        >
          <IconPencil />
        </button>
      ) : null}
    </div>
  );

  if (draft === null) return head;

  const hint = planNameHint(draft);
  const fieldId = `${idPrefix}-name`;

  return (
    <>
      {head}
      <label className="ct-app__field" htmlFor={fieldId}>
        Plan name
        <input
          id={fieldId}
          ref={fieldRef}
          className="ct-app__input"
          type="text"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
      </label>
      {hint === null ? null : <p className="ct-app__error">{hint}</p>}
      {rename.isError ? (
        <p className="ct-app__error" role="alert">
          {renameFailure(rename.error)}
        </p>
      ) : null}
      <div className="ct-app__actions">
        {hint === null ? (
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            disabled={rename.isPending}
            onClick={() => {
              void save(draft);
            }}
          >
            {rename.isPending ? 'Saving…' : 'Save this name'}
          </button>
        ) : null}
        <button
          type="button"
          className="ct-app__button"
          onClick={() => {
            setDraft(null);
          }}
        >
          Cancel
        </button>
      </div>
    </>
  );
}
