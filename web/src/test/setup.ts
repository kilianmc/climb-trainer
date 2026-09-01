import '@testing-library/jest-dom/vitest';

// jsdom implements almost none of the device APIs the session player will need.
// Stubs land here as those features arrive (wakeLock, AudioContext, vibrate,
// onLine) — mirroring the convention already used in portfolio-shell.

// TanStack Router scrolls on navigation and jsdom has no scrollTo, which otherwise
// prints "Not implemented" for every router test. Guarded because setup files also run
// for `@vitest-environment node` files, which have no `window`.
if (typeof window !== 'undefined') {
  window.scrollTo = () => undefined;
}

/**
 * Every stub below is installed **configurable and writable**, so a test can delete or replace
 * it and drive the *unavailable* branch — which is the branch that actually ships: Firefox on
 * Android has no `wakeLock`, an iOS PWA below 18.4 has one that never holds, and the iOS
 * hardware silent switch mutes Web Audio outright. Those paths must be as testable as the
 * happy one, so nothing here is a bare assignment.
 */
function install(target: object, key: string, value: unknown): void {
  Object.defineProperty(target, key, { value, configurable: true, writable: true });
}

/** A `WakeLockSentinel` with the one behaviour that matters: the OS can release it. */
export class FakeWakeLockSentinel extends EventTarget {
  readonly type = 'screen';
  released = false;

  release(): Promise<void> {
    this.osRelease();
    return Promise.resolve();
  }

  /** What the OS does when the tab is backgrounded — the reason the toggle reads the sentinel. */
  osRelease(): void {
    if (this.released) return;
    this.released = true;
    this.dispatchEvent(new Event('release'));
  }
}

/** Oscillators are the assertion surface: a cue is "how many tones, at which frequencies". */
export class FakeOscillator extends EventTarget {
  type: OscillatorType = 'sine';
  readonly frequency = { value: 0, setValueAtTime: () => undefined };
  startedAt: number | null = null;
  stoppedAt: number | null = null;

  connect<T>(destination: T): T {
    return destination;
  }
  disconnect(): void {}
  start(when: number): void {
    this.startedAt = when;
  }
  stop(when: number): void {
    this.stoppedAt = when;
  }
}

class FakeGainParam {
  setValueAtTime(): void {}
  linearRampToValueAtTime(): void {}
}

class FakeGain {
  readonly gain = new FakeGainParam();
  connect<T>(destination: T): T {
    return destination;
  }
  disconnect(): void {}
}

/** Constructed contexts land in `audioContexts` so a test can count them without a spy. */
export class FakeAudioContext {
  static readonly instances: FakeAudioContext[] = [];
  readonly destination = {};
  readonly oscillators: FakeOscillator[] = [];
  currentTime = 0;
  state: AudioContextState = 'suspended';
  closed = false;

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  createOscillator(): FakeOscillator {
    const oscillator = new FakeOscillator();
    this.oscillators.push(oscillator);
    return oscillator;
  }
  createGain(): FakeGain {
    return new FakeGain();
  }
  resume(): Promise<void> {
    this.state = 'running';
    return Promise.resolve();
  }
  close(): Promise<void> {
    this.closed = true;
    this.state = 'closed';
    return Promise.resolve();
  }
}

if (typeof window !== 'undefined') {
  install(window, 'AudioContext', FakeAudioContext);
  install(navigator, 'wakeLock', {
    request: () => Promise.resolve(new FakeWakeLockSentinel()),
  });
  install(navigator, 'vibrate', () => true);
  // jsdom hard-codes `onLine` to true on the prototype; redefining it on the instance is what
  // lets an `online`-trigger test say the tab was ever offline.
  install(navigator, 'onLine', true);
}
