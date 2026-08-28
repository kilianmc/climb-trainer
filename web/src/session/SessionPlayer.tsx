import type { ReactNode } from 'react';

import {
  IconCheck,
  IconCross,
  IconEndPhase,
  IconNextSet,
  IconPause,
  IconPlay,
  IconRestart,
} from '../ui/icons';

import { ItemRow } from './ItemRow';
import { KeepScreenOn } from './KeepScreenOn';
import type { CompiledPhase } from './protocol';
import { SoundToggle } from './SoundToggle';
import type { ItemView, ResyncNotice, SessionRun } from './useSessionRun';
import { formatElapsed } from './useSessionRun';

/**
 * The run itself: one thing at a time, over a bottom control bar.
 *
 * ⚠️ **Starting the session started no timer.** The big coloured face appears only while an
 * ITEM is running; the rest of the time the screen is the list, because "I am doing this
 * session" and "I am doing this block right now" are two different claims and the player used
 * to conflate them by counting down the moment Start was pressed.
 *
 * ⚠️ **FOCUS MODE: while an item is running the others are ABSENT, not dimmed.** A climber
 * mid-hang has one decision to make and the screen has to be readable at arm's length with
 * chalk on their hands — a list of five other blocks under the countdown is five wrong buttons
 * within reach. The list comes back the moment nothing is running, which is also the only
 * moment another item can be entered.
 *
 * ⚠️ **The number is NOT rendered from state.** `countdownRef` is attached to the countdown node
 * and `useSessionRun` writes its `textContent` per frame; a `setState` at 60 Hz re-renders the
 * whole tree sixty times a second. `initialClockText` is here only so the first paint is right.
 *
 * ⚠️ **The phase goes in `data-phase`, never in an interpolated class name.** See `_session.scss`
 * — `` `ct-app__player--${phase}` `` is `markupCss.test.ts`'s one blind spot and would trip it in
 * both directions at once. The item's state is `data-state` for the same reason.
 */
export function SessionPlayer({ run, readOnly }: { run: SessionRun; readOnly: boolean }) {
  const phase = run.phase;
  const isOpen = phase?.kind === 'open';
  const activeBlockIndex = run.run?.activeBlockIndex ?? null;
  const active =
    activeBlockIndex === null
      ? null
      : (run.items.find((item) => item.blockIndex === activeBlockIndex) ?? null);

  return (
    <div className="ct-app__bleed ct-app__player" data-phase={phase?.kind ?? 'idle'}>
      {/* The two corners. Neither is a primary action — CLAUDE.md's rule is that those live in
          the bottom bar, and both of these are settings the climber owns rather than steps in
          the session. Two wrappers rather than one flex row, so a hidden control leaves its
          corner empty instead of pulling the other one across the screen. */}
      <div className="ct-app__player-top">
        <div className="ct-app__player-corner">
          <SoundToggle
            available={run.cuesAvailable}
            soundOn={run.soundOn}
            onToggle={run.toggleSound}
          />
        </div>
        <div className="ct-app__player-corner">
          {/* ⚠️ `held`, the sentinel's real state — never the click. See `KeepScreenOn`. */}
          <KeepScreenOn
            available={run.wakeLock.available}
            held={run.wakeLock.held}
            onToggle={run.toggleKeepScreenOn}
          />
        </div>
      </div>

      {/* Its own row, so the banner pushes the countdown down rather than covering it: a climber
          who has just come back to the screen needs to read BOTH. */}
      {run.resync === null ? (
        <div />
      ) : (
        <ResyncBanner
          resync={run.resync}
          onKeepGoing={run.keepGoing}
          onRestart={run.restartPhase}
        />
      )}

      <div className="ct-app__player-body">
        {phase === null ? null : isOpen ? (
          <button
            type="button"
            className="ct-app__player-face ct-app__player-tap"
            onClick={() => {
              run.completeOpenPhase();
            }}
          >
            <PhaseFace phase={phase} run={run} />
          </button>
        ) : (
          <div className="ct-app__player-face">
            <PhaseFace phase={phase} run={run} />
          </div>
        )}

        {active === null ? (
          <ItemList run={run} />
        ) : (
          <div className="ct-app__player-controls">
            <ItemControls item={active} run={run} />
          </div>
        )}
      </div>

      {/* ⚠️ Focus mode reaches the BAR too: no session-level action inside a running item, which
          is where Kilian found Finish. Empty rather than absent, so the four grid rows hold. */}
      {active === null ? (
        <div className="ct-app__player-bar">
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={run.finish}
          >
            {/* Issue #65 by absence: in demo scope there is no save, so the control does not
                claim one. */}
            {readOnly ? 'End session' : 'Finish'}
          </button>
        </div>
      ) : (
        <div />
      )}
    </div>
  );
}

/**
 * The session, as the list of things it is. Rendered only while nothing is running — see the
 * focus-mode note above.
 *
 * ⚠️ **Nothing here is ever `disabled`.** Completed and skipped are states the climber can move
 * between freely — the whole point of the restart control is that a block marked done can be
 * done properly — and a greyed-out control in demo scope is the thing issue #65 refuses.
 * `aria-pressed` carries which one is current instead.
 */
function ItemList({ run }: { run: SessionRun }) {
  return (
    <ol className="ct-app__items">
      {run.items.map((item) => (
        <ItemRow key={item.blockIndex} item={item}>
          <ItemControls item={item} run={run} />
        </ItemRow>
      ))}
    </ol>
  );
}

/**
 * One icon-only control. `ui/ThemeSwitch.tsx`'s contract, on every one of them: the accessible
 * name says what pressing DOES, the `title` gives a pointer the same words, and `--ct-tap`'s
 * 44px floor comes from `&__button--icon`. Never `disabled` (issue #65).
 */
function Control({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className="ct-app__button ct-app__button--icon"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/**
 * An item's controls, icon-only, and the same component in the list and in focus mode.
 *
 * ⚠️ **Each label names its own item.** In the list there are as many of these rows as there are
 * blocks, so three buttons reading "Completed" would be three identical accessible names on one
 * screen. It costs nothing in focus mode and it is one rule instead of two.
 *
 * The two pause-adjacent controls are running-only because they have nothing to act on
 * otherwise, and **"next set" is hidden on the last set and on a single-set item** — there is no
 * next set to land on, and `nextSetAvailable` answers that from the timeline rather than from a
 * count.
 */
function ItemControls({ item, run }: { item: ItemView; run: SessionRun }) {
  const running = item.status === 'running';
  const pauseLabel = `${run.paused ? 'Resume' : 'Pause'} ${item.label}`;
  // An `open` phase belongs to the item in play, so its bail-out does too. Never true in the
  // list: no item is running there, which is the only state the list is rendered in.
  const bailable = running && run.phase?.kind === 'open';

  return (
    <div className="ct-app__item-actions">
      {running ? (
        <>
          <Control label={pauseLabel} onClick={run.togglePause}>
            {run.paused ? <IconPlay /> : <IconPause />}
          </Control>
          {run.nextSetAvailable ? (
            <Control label={`Skip to the next set of ${item.label}`} onClick={run.nextSet}>
              <IconNextSet />
            </Control>
          ) : null}
          {/* The untimed effort's way out, and it mints no set — unlike "next set", which logs
              the ones it crosses. It used to sit in the session bar; see the note there. */}
          {bailable ? (
            <Control label={`Didn’t finish ${item.label}`} onClick={run.skipOpenPhase}>
              <IconEndPhase />
            </Control>
          ) : null}
        </>
      ) : null}
      {/* A restart is available on a RUNNING item too: "I didn't do it but I had to finish it
          for whatever reason" is a mid-set decision, not one made after the fact. */}
      <Control
        label={`${item.status === 'pending' ? 'Start' : 'Restart'} ${item.label}`}
        onClick={() => {
          run.startItem(item.blockIndex);
        }}
      >
        {item.status === 'pending' ? <IconPlay /> : <IconRestart />}
      </Control>
      <Control
        label={running ? `Mark ${item.label} completed` : `I did ${item.label} myself`}
        pressed={item.status === 'completed'}
        onClick={() => {
          run.completeItem(item.blockIndex);
        }}
      >
        <IconCheck />
      </Control>
      <Control
        label={`Mark ${item.label} skipped`}
        pressed={item.status === 'skipped'}
        onClick={() => {
          run.skipItem(item.blockIndex);
        }}
      >
        <IconCross />
      </Control>
    </div>
  );
}

/** Which phase, which set, and the clock. Shared by the tappable and the timed region. */
function PhaseFace({ phase, run }: { phase: CompiledPhase | null; run: SessionRun }) {
  // Aliased out of the prop (`react-hooks/immutability`), and a CALLBACK ref because
  // `countdownRef` is typed for any `HTMLElement` and React's `ref` prop is invariant.
  const { countdownRef } = run;
  return (
    <>
      <span className="ct-app__player-phase">{run.paused ? 'Paused' : phaseName(phase)}</span>
      {phase === null ? null : <span className="ct-app__player-label">{phase.label}</span>}
      <span
        className="ct-app__player-count"
        ref={(node) => {
          countdownRef.current = node;
        }}
      >
        {run.initialClockText}
      </span>
      <span className="ct-app__player-step">{stepLine(phase, run)}</span>
    </>
  );
}

function phaseName(phase: CompiledPhase | null): string {
  if (phase === null) return 'Ready';
  if (phase.kind === 'prepare') return 'Get ready';
  if (phase.kind === 'work') return 'Work';
  if (phase.kind === 'rest') return 'Rest';
  return 'Go';
}

function stepLine(phase: CompiledPhase | null, run: SessionRun): string {
  if (phase === null) return 'Pick something below when you are ready.';
  if (run.paused) return 'The clock is stopped. Press play when you are back.';
  if (phase.kind === 'open') return 'Tap anywhere when you are done';
  if (phase.setOfBlock === null) {
    return `Phase ${String(run.phaseIndex + 1)} of ${String(run.phaseCount)}`;
  }
  return `Set ${String(phase.setOfBlock)} of ${String(phase.setsInBlock)}`;
}

/** Non-modal on purpose: the timer is already right, so this is information rather than a
 *  decision. "Restart this phase" is safe because tab-hidden is itself a flush trigger. */
function ResyncBanner({
  resync,
  onKeepGoing,
  onRestart,
}: {
  resync: ResyncNotice;
  onKeepGoing: () => void;
  onRestart: () => void;
}) {
  const landed = resync.landedOn;
  return (
    <div className="ct-app__player-banner" role="status">
      <span>
        {resync.awayMs === null
          ? 'The timer moved on while this screen was away'
          : `You were away for ${formatElapsed(resync.awayMs)} — the timer moved on`}
        {landed === null
          ? ' to the end of this part.'
          : landed.setOfBlock === null
            ? '.'
            : ` to ${landed.kind === 'work' ? 'set' : 'the rest after set'} ${String(landed.setOfBlock)} of ${String(landed.setsInBlock)}.`}
      </span>
      <button type="button" className="ct-app__button" onClick={onKeepGoing}>
        Keep going
      </button>
      <button type="button" className="ct-app__button" onClick={onRestart}>
        Restart this phase
      </button>
    </div>
  );
}
