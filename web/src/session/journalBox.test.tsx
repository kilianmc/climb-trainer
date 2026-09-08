import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Profile } from '../api/types';

import { SessionJournal } from './SessionJournal';
import { SessionNotes } from './SessionNotes';
import type { JournalDraft } from './runStore';
import { EMPTY_JOURNAL_DRAFT } from './runStore';
import type { SessionRun } from './useSessionRun';

/** The box's two non-wire rules: `show_body_metrics` off means the weigh-in is ABSENT, and no
 *  copy frames weight as reducible. ⚠️ The schema guard walks NAMES, so it sees neither. */

let profile: Profile | undefined;

vi.mock('../profile/api', () => ({
  useProfileView: () => ({ profile, isLoadingError: false, retry: () => undefined }),
}));

const BASE_PROFILE: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: 11,
  current_grade_id: null,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

/** The box reads exactly these four members of `SessionRun`. Cast once, here, so adding a
 *  fifth is a TypeScript error in this file rather than a silent `undefined` at runtime. */
function fakeRun(journal: Partial<JournalDraft> = {}): SessionRun {
  return {
    journal: { ...EMPTY_JOURNAL_DRAFT, ...journal },
    setJournalDraft: vi.fn(),
    saveJournal: vi.fn(),
    isSavingJournal: false,
  } as unknown as SessionRun;
}

const WEIGH_IN = /weight today/i;

afterEach(() => {
  profile = undefined;
  vi.restoreAllMocks();
});

describe('the show_body_metrics gate', () => {
  it('asks for a weigh-in when the setting is on', () => {
    profile = BASE_PROFILE;
    render(<SessionJournal run={fakeRun()} readOnly={false} />);
    expect(screen.getByLabelText(WEIGH_IN)).toBeTruthy();
  });

  it('asks for NOTHING about weight when the setting is off', () => {
    profile = { ...BASE_PROFILE, show_body_metrics: false };
    render(<SessionJournal run={fakeRun()} readOnly={false} />);
    expect(screen.queryByLabelText(WEIGH_IN)).toBeNull();
    // Absent, not disabled: #65's rule, and the only reading of "nothing prompts for one".
    expect(document.body.innerHTML).not.toMatch(/scale said/i);
    // The rest of the box is untouched — the gate must not take the diary with it.
    expect(screen.getByLabelText(/how it went/i)).toBeTruthy();
  });

  it('asks for nothing about weight while the profile is UNREAD', () => {
    // ⚠️ Erring toward not asking is the only safe direction for this one setting, even though
    // the column's server default is TRUE.
    profile = undefined;
    render(<SessionJournal run={fakeRun()} readOnly={false} />);
    expect(screen.queryByLabelText(WEIGH_IN)).toBeNull();
  });
});

describe('the box tells the truth about the write', () => {
  it('offers no save control at all with nothing typed', () => {
    // ⚠️ ABSENT, not disabled: `buildJournalPut` returns `null` for an empty draft, so the
    // control could only refuse itself — and Kilian read a live button as an unsaved entry.
    profile = BASE_PROFILE;
    render(<SessionJournal run={fakeRun()} readOnly={false} />);
    expect(screen.queryAllByRole('button')).toEqual([]);
  });

  it('says the words are still here after a refusal, not that they are gone', () => {
    profile = BASE_PROFILE;
    render(
      <SessionJournal
        run={fakeRun({ body: 'unlucky payload', refusedAtEpochMs: 1 })}
        readOnly={false}
      />,
    );
    expect(screen.getByRole('alert').textContent).toMatch(/still here/i);
    expect(screen.getByLabelText(/how it went/i)).toHaveProperty('value', 'unlucky payload');
  });

  it('distinguishes unsent from saved, rather than collapsing both into a spinner', () => {
    profile = BASE_PROFILE;
    const { unmount } = render(
      <SessionJournal run={fakeRun({ body: 'queued' })} readOnly={false} />,
    );
    expect(screen.getByRole('alert').textContent).toMatch(/not sent yet/i);
    unmount();

    render(
      <SessionJournal run={fakeRun({ body: 'queued', savedAtEpochMs: 1 })} readOnly={false} />,
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(document.body.textContent).toMatch(/saved to your diary/i);
  });
});

/** Every state of the one control, as RENDERED. `savedAtEpochMs` is what an edit clears and
 *  `entryId` is what it must not, so those two together are the whole state machine. */
const OFFER_CASES: [string, Partial<JournalDraft>, string | null][] = [
  ['nothing written yet', {}, null],
  ['written, never saved', { body: 'words' }, 'Save this entry'],
  ['saved and unchanged', { body: 'words', savedAtEpochMs: 1, entryId: 5 }, null],
  ['saved, then edited', { body: 'words, plus more', entryId: 5 }, 'Update this entry'],
  ['refused, not yet edited', { body: 'words', refusedAtEpochMs: 1 }, null],
  // ⚠️ A 4xx stored NOTHING, so that press CREATES a row: Save, never Update. The arm whose
  // label is easiest to get wrong, and the reason `entryId` is not a "has been saved" boolean.
  ['refused, then edited', { body: 'words, plus more' }, 'Save this entry'],
];

describe('the save control tells the truth about what the press would do', () => {
  it.each(OFFER_CASES)('%s', (_name, journal, label) => {
    profile = BASE_PROFILE;
    render(<SessionJournal run={fakeRun(journal)} readOnly={false} />);
    // The WHOLE set of buttons in the box, so "no control at all" is what gets proven.
    expect(screen.queryAllByRole('button').map((button) => button.textContent)).toEqual(
      label === null ? [] : [label],
    );
  });

  it('keeps the confirmation that it is stored once the control is gone', () => {
    profile = BASE_PROFILE;
    render(
      <SessionJournal
        run={fakeRun({ body: 'words', savedAtEpochMs: 1, entryId: 5 })}
        readOnly={false}
      />,
    );
    expect(document.body.textContent).toMatch(/saved to your diary/i);
    expect(screen.queryAllByRole('button')).toEqual([]);
  });

  it('says Updating…, not Saving…, while an update is in flight', () => {
    profile = BASE_PROFILE;
    const run = { ...fakeRun({ body: 'words', entryId: 5 }), isSavingJournal: true };
    render(<SessionJournal run={run} readOnly={false} />);
    // In flight the control STAYS, disabled — removing it mid-press is what strands focus.
    expect(screen.getByRole('button').textContent).toBe('Updating…');
  });
});

describe('the vanishing control must not strand keyboard focus', () => {
  const SAVED = { body: 'words', savedAtEpochMs: 1, entryId: 5 };

  it('puts focus back in the diary when the pressed control is removed', () => {
    profile = BASE_PROFILE;
    const { rerender } = render(
      <SessionJournal run={fakeRun({ body: 'words' })} readOnly={false} />,
    );
    const save = screen.getByRole('button', { name: /save this entry/i });
    save.focus();
    expect(document.activeElement).toBe(save);

    rerender(<SessionJournal run={fakeRun(SAVED)} readOnly={false} />);
    expect(screen.queryAllByRole('button')).toEqual([]);
    // ⚠️ `<body>` is where React drops it, and that loses a keyboard user's place entirely.
    expect(document.activeElement).toBe(screen.getByLabelText(/how it went/i));
  });

  it('does NOT take focus from wherever the user actually went', () => {
    profile = BASE_PROFILE;
    const { rerender } = render(
      <SessionJournal run={fakeRun({ body: 'words' })} readOnly={false} />,
    );
    const feel = screen.getByLabelText(/how you feel/i);
    feel.focus();
    rerender(<SessionJournal run={fakeRun(SAVED)} readOnly={false} />);
    expect(document.activeElement).toBe(feel);
  });

  it('takes no focus at all on a first render of an entry already saved', () => {
    profile = BASE_PROFILE;
    render(<SessionJournal run={fakeRun(SAVED)} readOnly={false} />);
    expect(document.activeElement).toBe(document.body);
  });
});

/** ⚠️ Matched against RENDERED markup, never the source: the source NAMES these words in order
 *  to forbid them, and a guard that reads a prohibition as a violation gets deleted at once. */
const FORBIDDEN_COPY = [
  'lose',
  'losing',
  'lighter',
  'leaner',
  'slimmer',
  'shed',
  'overweight',
  'goal weight',
  'target weight',
  'ideal weight',
  'racing weight',
  'climbing weight',
  'bmi',
  'body fat',
];

describe('the app never recommends losing weight', () => {
  it.each([
    ['weigh-in shown, nothing typed', true, {}],
    ['weigh-in shown, a weight typed', true, { bodyWeightKg: '71.4' }],
    ['weigh-in shown, an impossible weight typed', true, { bodyWeightKg: '9' }],
    ['weigh-in hidden', false, { body: 'words', savedAtEpochMs: 1 }],
    ['refused', true, { body: 'words', refusedAtEpochMs: 1 }],
    ['changed since saved, so the control says Update', true, { body: 'words', entryId: 5 }],
  ])('says nothing about reducing it: %s', (_name, metrics, journal) => {
    profile = { ...BASE_PROFILE, show_body_metrics: metrics };
    const { container } = render(
      <SessionJournal run={fakeRun(journal as Partial<JournalDraft>)} readOnly={false} />,
    );
    // `innerHTML`, so a `placeholder` or an `aria-label` is covered too, not just text nodes.
    const copy = container.innerHTML.toLowerCase();
    for (const banned of FORBIDDEN_COPY) {
      expect(copy, `"${banned}" is in this box's copy`).not.toContain(banned);
    }
  });

  it('says nothing about reducing it on the demo account either', () => {
    profile = BASE_PROFILE;
    const { container } = render(<SessionJournal run={fakeRun()} readOnly={true} />);
    const copy = container.innerHTML.toLowerCase();
    for (const banned of FORBIDDEN_COPY) {
      expect(copy, `"${banned}" is in this box's copy`).not.toContain(banned);
    }
  });

  it('would CATCH such a sentence — the wordlist is not vacuous', () => {
    // ⚠️ The positive control. Every arm above asserts an ABSENCE, and an absence over a
    // wordlist that matches nothing reads green for ever.
    const sample =
      'Your goal weight is 65 kg — lose 6 kg to be a lighter, leaner climber; ' +
      'losing it lowers your BMI.';
    const hits = FORBIDDEN_COPY.filter((banned) => sample.toLowerCase().includes(banned));
    expect(hits).toEqual(['lose', 'losing', 'lighter', 'leaner', 'goal weight', 'bmi']);
  });
});

/** The SECOND placement, proven here because the sheet has no content of its own — it IS this
 *  box. ⚠️ Its pause half needs a clock and lives in `sessionPlayer.test.tsx`. */
function NotesHarness({
  open,
  onClose,
  run,
}: {
  open: boolean;
  onClose: () => void;
  run: SessionRun;
}) {
  return (
    <>
      <button type="button">open the notes</button>
      {/* The background, in one control: a Tab that reaches this has left the sheet. */}
      <button type="button">background control</button>
      {open ? <SessionNotes run={run} readOnly={false} onClose={onClose} /> : null}
    </>
  );
}

describe('the notes overlay', () => {
  it('is a modal dialog, named by the words already on screen', () => {
    profile = BASE_PROFILE;
    render(<NotesHarness open onClose={vi.fn()} run={fakeRun()} />);
    // ⚠️ `aria-labelledby` the box's own heading, so there is no second copy of the title to
    // fall out of step with it — `JOURNAL_HEADING_ID` is the one constant behind both ends.
    const sheet = screen.getByRole('dialog', { name: /anything worth writing down/i });
    expect(sheet).toHaveAttribute('aria-modal', 'true');
  });

  it('renders the SAME box against the SAME draft, never a second form', () => {
    profile = BASE_PROFILE;
    const run = fakeRun({ body: 'started mid-session' });
    render(<NotesHarness open onClose={vi.fn()} run={run} />);
    const sheet = within(screen.getByRole('dialog'));
    expect(sheet.getByLabelText(/how it went/i)).toHaveProperty('value', 'started mid-session');

    fireEvent.change(sheet.getByLabelText(/how it went/i), { target: { value: 'and more' } });
    // The run's own draft — the one the summary reads — and not overlay-local state.
    expect(vi.mocked(run.setJournalDraft)).toHaveBeenCalledWith({ body: 'and more' });
  });

  it('moves focus into the sheet and back to the control that opened it', () => {
    profile = BASE_PROFILE;
    const onClose = vi.fn();
    const run = fakeRun();
    const { rerender } = render(<NotesHarness open={false} onClose={onClose} run={run} />);
    const opener = screen.getByRole('button', { name: 'open the notes' });
    opener.focus();

    rerender(<NotesHarness open onClose={onClose} run={run} />);
    expect(document.activeElement).toBe(screen.getByRole('dialog'));

    // ⚠️ Back to the OPENER, not to `<body>`: a keyboard user who closes the sheet has to land
    // where they were, and the opener is still mounted behind it precisely so they can.
    rerender(<NotesHarness open={false} onClose={onClose} run={run} />);
    expect(document.activeElement).toBe(opener);
  });

  it('offers a VISIBLE way out, and Escape as well', () => {
    profile = BASE_PROFILE;
    const onClose = vi.fn();
    render(<NotesHarness open onClose={onClose} run={fakeRun()} />);

    // The visible control is the primary way out: in the federated mount the shell's own hook
    // takes Escape first, which is accepted (Kilian) rather than worked around.
    fireEvent.click(screen.getByRole('button', { name: 'Close the notes' }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('wraps Tab inside the sheet in both directions, so the background is unreachable', () => {
    profile = BASE_PROFILE;
    render(<NotesHarness open onClose={vi.fn()} run={fakeRun({ body: 'words' })} />);
    const sheet = screen.getByRole('dialog');
    const stops = [...sheet.querySelectorAll<HTMLElement>('button, input, select, textarea')];
    const first = stops[0];
    const last = stops.at(-1);
    // Not vacuous: the sheet holds a whole form, and the way out, so wrapping is a real move.
    expect(stops.length).toBeGreaterThan(3);

    last?.focus();
    fireEvent.keyDown(last ?? sheet, { key: 'Tab' });
    expect(document.activeElement).toBe(first);

    first?.focus();
    fireEvent.keyDown(first ?? sheet, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);

    // The whole point, stated as itself: whatever the wrap did, it stayed inside the sheet.
    expect(sheet.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(
      screen.getByRole('button', { name: 'background control' }),
    );
  });

  it('lands on the first control from the sheet itself, which is not a Tab stop', () => {
    profile = BASE_PROFILE;
    render(<NotesHarness open onClose={vi.fn()} run={fakeRun({ body: 'words' })} />);
    const sheet = screen.getByRole('dialog');
    // Focus is on the sheet, where the open put it — `tabindex="-1"`, so the first Tab has to
    // move INWARD rather than out to the background behind it.
    expect(document.activeElement).toBe(sheet);
    fireEvent.keyDown(sheet, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByLabelText(/how it went/i));
  });
});
