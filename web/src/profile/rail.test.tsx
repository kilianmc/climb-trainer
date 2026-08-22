import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { ProfileProgress, type ProgressNode } from './ProfileProgress';

/**
 * The progress rail's accessibility contract.
 *
 * ⚠️ **This file exists because the step LIST was deleted** (issue #54, round 10).
 * `OnboardingStepper` used to be the canonical stepper and it carried CLAUDE.md's fixed
 * `<nav>` → `<ol>` → `<li>` + `aria-current="step"` contract. Deleting it moved that contract
 * into `ProfileProgress`'s rail, which is now BOTH the progress visual and the stepper — and a
 * contract that moved with no test moved onto the floor.
 *
 * It is a UI test, which the testing policy is normally against, and the policy's own
 * exclusion is "a card that renders the props it was given". None of what is asserted here is
 * that:
 *
 * - **The names are the only thing a non-sighted reader gets.** The visible content of a node
 *   is a digit. A row of circles labelled "0" to "3" is a row of *unlabelled* circles to
 *   anyone not looking at it, and nothing in the type system or in a lint rule says otherwise.
 * - **The nesting is an ARIA validity question, not a layout one.** A `role="progressbar"`
 *   element's contents are presentational, so putting focusable nodes inside it is invalid —
 *   and "move the rail inside the track" is exactly the tidy-up a future agent would reach
 *   for, because visually the nodes SIT ON the spine.
 * - **The honesty invariant is a domain rule** ("a mechanic is allowed only if the progress it
 *   signals is TRUE"): the rail must never read complete while a real step is unanswered, and
 *   it must never disagree with the number it is drawn beside.
 *
 * What is deliberately NOT asserted: class names, copy, colours, the connectors' fill state,
 * or anything `_profile.scss` owns. `styles/contrast.test.ts` and `styles/designGuard.test.ts`
 * are the guards for that layer.
 */

/** The wizard's own shape: node 0 is the inert Account, then the four steps. */
function wizardNodes(
  overrides: Partial<Record<string, Partial<ProgressNode>>> = {},
): ProgressNode[] {
  const base: ProgressNode[] = [
    { label: 'Account', done: true },
    { label: 'Your goal', done: true, current: false, onGo: vi.fn() },
    { label: 'Availability', done: true, current: true, onGo: vi.fn() },
    { label: 'Where you are now', done: false, current: false, onGo: vi.fn() },
    { label: 'Injuries', done: false, current: false, onGo: vi.fn() },
  ];
  return base.map((node) => ({ ...node, ...overrides[node.label] }));
}

/** Every node's element, in document order, whether it rendered as a button or as a span. */
function nodeElements(): HTMLElement[] {
  const items = screen.getAllByRole('listitem');
  return items.map((item) => {
    const node = item.querySelector<HTMLElement>('button, [role="img"]');
    if (node === null) throw new Error(`a rail item rendered no node: ${item.outerHTML}`);
    return node;
  });
}

const nameOf = (element: HTMLElement) => element.getAttribute('aria-label') ?? '';

it('renders the rail as a labelled nav of an ordered list, one item per node', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  // The landmark, and it has to be NAMED: a page can hold more than one nav.
  const nav = screen.getByRole('navigation', { name: 'Profile steps' });
  const list = screen.getByRole('list');
  expect(nav).toContainElement(list);
  expect(list.tagName).toBe('OL');
  // An ordered list, because the steps have an order and it is the order they are asked in.
  expect(screen.getAllByRole('listitem')).toHaveLength(5);
  for (const item of screen.getAllByRole('listitem')) expect(list).toContainElement(item);
});

it('marks the current step, and only the current step, with aria-current', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  const current = document.querySelectorAll('[aria-current]');
  expect(current).toHaveLength(1);
  expect(current[0]).toHaveAttribute('aria-current', 'step');
  expect(nameOf(current[0] as HTMLElement)).toMatch(/^Step 2: Availability/);
});

it('names the progressbar and reports the caller percent verbatim', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  // Named via `aria-labelledby` -> the visible label, so the announced and the sighted name
  // cannot drift. A nameless progressbar announces "60 percent" of nothing.
  const bar = screen.getByRole('progressbar', { name: 'Profile completion' });
  expect(bar).toHaveAttribute('aria-valuenow', '60');
  expect(bar).toHaveAttribute('aria-valuemin', '0');
  expect(bar).toHaveAttribute('aria-valuemax', '100');

  // ⚠️ The reported value is `percent`, NOT arithmetic on how many nodes are filled. Two of
  // the four steps are done here, which is 60% — but the rail's own geometry rounds to a node
  // edge, and rounding the announced value to match it would turn a real number into a made-up
  // one. Nothing about the nodes may feed back into this attribute.
  expect(bar).toHaveAttribute('aria-valuenow', '60');
});

it('keeps the nodes as SIBLINGS of the progressbar, never as children of it', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  const bar = screen.getByRole('progressbar', { name: 'Profile completion' });
  const nav = screen.getByRole('navigation', { name: 'Profile steps' });

  // ⚠️ The structural assertion, not merely the attribute one. A `role="progressbar"`
  // element's contents are presentational, so a focusable child inside it is invalid ARIA —
  // and these are real buttons with real names. Visually the nodes sit ON the spine, which is
  // exactly why "just nest them" is the refactor this guards against.
  expect(bar).not.toContainElement(nav);
  expect(bar.querySelector('button, [role="img"], nav, ol, li')).toBeNull();
  expect(nav.parentElement).toBe(bar.parentElement);
});

it('gives every node a name that says which step it is and whether it is answered', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  // Numbered from ZERO: step 0 is the account, and it is what the 20% floor credits.
  expect(nodeElements().map(nameOf)).toEqual([
    'Step 0: Account — done',
    'Step 1: Your goal — done',
    'Step 2: Availability — done',
    'Step 3: Where you are now — not answered yet',
    'Finish — step 4: Injuries — not answered yet',
  ]);
});

it('draws the last node as Finish and leads its accessible name with that word', () => {
  render(<ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />);

  const nodes = nodeElements();
  const last = nodes[nodes.length - 1];
  expect(last).toBeDefined();
  if (last === undefined) return;

  // WCAG 2.5.3 Label in Name: the visible text must be CONTAINED in the accessible name, and
  // leading with it is what makes "Finish" usable by voice control.
  expect(last).toHaveTextContent('Finish');
  expect(nameOf(last)).toMatch(/^Finish\b/);
  // It is the last STEP wearing a word, not a fifth node summarising the other four.
  expect(nameOf(last)).toContain('Injuries');
  // The others wear their digit.
  expect(nodes.slice(0, -1).map((node) => node.textContent)).toEqual(['0', '1', '2', '3']);
});

it('renders a node with no destination as an inert element, and one with a destination as a button', () => {
  const onGo = vi.fn();
  render(
    <ProfileProgress
      percent={60}
      label="Profile completion"
      nodes={wizardNodes({ 'Your goal': { onGo } })}
    />,
  );

  // ⚠️ Step 0 has nowhere to go in the wizard — there is no Account card — and a DISABLED
  // button is still announced as a control. So it is not a control at all.
  const account = screen.getByRole('img', { name: 'Step 0: Account — done' });
  expect(account.tagName).not.toBe('BUTTON');
  expect(account).not.toHaveAttribute('disabled');

  // Four steps, four buttons: the rail is the wizard's navigation as well as its bar.
  expect(screen.getAllByRole('button')).toHaveLength(4);
  const goal = screen.getByRole('button', { name: 'Step 1: Your goal — done' });
  goal.click();
  expect(onGo).toHaveBeenCalledTimes(1);
});

/**
 * ⚠️ **The honesty invariant: the rail may never read complete while a real step is
 * unanswered.** This is the rule that governs the whole endowed-progress mechanic — a
 * mechanic is allowed only if the progress it signals is TRUE — and the rail is now the place
 * it can be broken, because the Finish node used to report what was outstanding ACROSS all
 * the steps rather than its own state. A node that summarised its siblings could read "done"
 * for a step nobody had answered.
 */
it.each([
  // Mid-flow, with a gap: a node after an unanswered one must not borrow its neighbours' state.
  { what: 'mid-flow', done: { 'Where you are now': { done: false }, Injuries: { done: true } } },
  // ⚠️ **The shape that catches the old Finish node, and the reason this is a table.** With
  // every earlier step answered, a Finish that reports across the rail and a Finish that
  // reports itself say the SAME thing for every other combination — this is the only row that
  // tells them apart, and the first draft of this test did not have it.
  { what: 'only the last step open', done: {} },
  // Answered out of order — the editor lets any section be filled in at any time.
  {
    what: 'answers out of order',
    done: { 'Your goal': { done: false }, Availability: { done: false } },
  },
])('never reads a node as done unless its own step is answered ($what)', ({ done }) => {
  const nodes = wizardNodes({
    // Everything answered except the last, then overridden per row.
    'Where you are now': { done: true },
    Injuries: { done: false },
    ...done,
  });
  render(<ProfileProgress percent={60} label="Profile completion" nodes={nodes} />);

  const names = nodeElements().map(nameOf);
  expect(names).toHaveLength(nodes.length);
  names.forEach((name, index) => {
    const node = nodes[index];
    expect(node).toBeDefined();
    if (node === undefined) return;
    expect(name).toContain(node.label);
    // Exactly one of the two states, and it is the node's OWN state — never a summary of its
    // siblings, which is what the Finish node used to be.
    expect(name.endsWith('— done')).toBe(node.done);
    expect(name.endsWith('— not answered yet')).toBe(!node.done);
  });

  // And every row above leaves at least one step open, so a rail that read complete here would
  // be reading complete with a real step unanswered.
  expect(names.some((name) => name.endsWith('— not answered yet'))).toBe(true);
});

it('does not let the rail disagree with the number beside it', () => {
  const { container } = render(
    <ProfileProgress percent={80} label="Profile completion" nodes={wizardNodes()} />,
  );

  // Two units for one fact is how a stepper starts disagreeing with a progress bar, so the
  // text and the announced value are asserted to be the same number.
  const bar = screen.getByRole('progressbar', { name: 'Profile completion' });
  expect(container).toHaveTextContent('80% complete');
  expect(bar).toHaveAttribute('aria-valuenow', '80');
});

it('renders the plain bar with no stepper landmark when it is given no nodes', () => {
  render(<ProfileProgress percent={20} label="Profile completion" />);

  // The dashboard's use: a bar, and no claim to be a stepper. A nav with no items would be a
  // landmark announcing nothing.
  expect(screen.getByRole('progressbar', { name: 'Profile completion' })).toHaveAttribute(
    'aria-valuenow',
    '20',
  );
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
});

it('keeps the live region in the DOM when there is nothing to announce', () => {
  const { container } = render(
    <ProfileProgress percent={60} label="Profile completion" nodes={wizardNodes()} />,
  );

  // Rendered ALWAYS, empty when silent: a live region added to the DOM at the same moment as
  // its text is frequently not announced at all.
  const live = container.querySelector('[aria-live="polite"]');
  expect(live).not.toBeNull();
  expect(live?.textContent).toBe('');
});
