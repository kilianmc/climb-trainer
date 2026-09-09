import { useCallback, useEffect, useRef, type ReactNode } from 'react';

/** The app's ONE overlay: focus in on open and back to the opener on close, Tab trapped, and a
 *  visible way out in the last row. Extracted from `SessionNotes`, which was the first. */

/** Everything inside the sheet a Tab could land on, in document order. A disabled control is
 *  excluded here rather than filtered after, so the in-flight Save button drops out on its own. */
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/** Tab, wrapped — the whole of "the background is unreachable by keyboard". ⚠️ The sheet is
 *  `tabindex="-1"` and so NOT a stop: at open `index` is `-1`, and the first Tab moves inward. */
function trapTab(panel: HTMLElement, event: React.KeyboardEvent): void {
  const stops = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)];
  if (stops.length === 0) {
    // Nothing to move to: hold focus on the sheet rather than hand it to the screen behind.
    event.preventDefault();
    return;
  }
  const index = stops.findIndex((stop) => stop === document.activeElement);
  const forward = !event.shiftKey;
  const leaving = index === -1 || (forward ? index === stops.length - 1 : index === 0);
  if (!leaving) return;
  event.preventDefault();
  const target = forward ? stops[0] : stops.at(-1);
  target?.focus();
}

/** `labelledBy` is the id of a heading ALREADY on screen inside the sheet — never a second copy
 *  of the title, which is how the two fall out of step. `actions` is the last row. */
export function Sheet({
  labelledBy,
  onClose,
  children,
  actions,
}: {
  labelledBy: string;
  onClose: () => void;
  children: ReactNode;
  actions: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  // ⚠️ The opener is read at MOUNT and refocused on unmount, so no ref has to be threaded
  // through the caller. `isConnected`: navigating away takes the opener with it.
  useEffect(() => {
    const opener = document.activeElement;
    panelRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>): void => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      const panel = panelRef.current;
      if (event.key === 'Tab' && panel !== null) trapTab(panel, event);
    },
    [onClose],
  );

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- a modal dialog's Escape and Tab trap belong on the sheet itself; there is no interactive element that could hold them, and the rule cannot tell this apart from a handler bolted onto a div in place of a button.
    <div
      ref={panelRef}
      className="ct-app__overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="ct-app__overlay-body">{children}</div>
      {/* Last row, so it is on screen however far the form has scrolled — the player's own rule
          that a primary action lives at the bottom, where a thumb reaches it. */}
      <div className="ct-app__overlay-bar">{actions}</div>
    </div>
  );
}
