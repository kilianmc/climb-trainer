import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeAudioContext } from '../test/setup';

import { audioCuesAvailable, createCueBus, cueForPhase, vibrationAvailable } from './cues';

/**
 * The cue bus, and the four ways it is allowed to do nothing.
 *
 * Every defect guarded here is one a climber never sees reported: a context built outside the
 * Start gesture (silent forever on iOS), a second context per session, a cue that throws
 * because `navigator.vibrate` is absent, and a bus that stops working because the audio
 * hardware refused. Audio is an enhancement — the failure mode to prevent is a *thrown*
 * exception taking the phase change with it, not a missing beep.
 */

function latestContext(): FakeAudioContext {
  const context = FakeAudioContext.instances.at(-1);
  if (context === undefined) throw new Error('no AudioContext was constructed');
  return context;
}

beforeEach(() => {
  FakeAudioContext.instances.length = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('the cue vocabulary', () => {
  it('collapses four phase kinds onto three cues', () => {
    expect(cueForPhase('work')).toBe('work');
    expect(cueForPhase('open')).toBe('work');
    expect(cueForPhase('rest')).toBe('rest');
    expect(cueForPhase('prepare')).toBe('rest');
    expect(cueForPhase(null)).toBe('finish');
  });

  it.each([
    ['work', 2, [880, 880]],
    ['rest', 1, [440]],
    ['finish', 3, [660, 550, 440]],
  ] as const)('%s is %i tone(s) at the documented frequencies', (cue, count, frequencies) => {
    const bus = createCueBus();
    bus.arm();
    bus.play(cue);
    const oscillators = latestContext().oscillators;
    expect(oscillators).toHaveLength(count);
    expect(oscillators.map((oscillator) => oscillator.frequency.value)).toEqual([...frequencies]);
  });

  it('schedules every tone with a start and a stop, in order', () => {
    const bus = createCueBus();
    bus.arm();
    bus.play('finish');
    for (const oscillator of latestContext().oscillators) {
      expect(oscillator.startedAt).not.toBeNull();
      expect(oscillator.stoppedAt).toBeGreaterThan(oscillator.startedAt ?? 0);
    }
  });
});

describe('the audio context', () => {
  it('is not constructed until arm(), which is what keeps it inside the Start gesture', () => {
    const bus = createCueBus();
    expect(bus.isArmed()).toBe(false);
    expect(FakeAudioContext.instances).toHaveLength(0);
    bus.arm();
    expect(bus.isArmed()).toBe(true);
    expect(FakeAudioContext.instances).toHaveLength(1);
  });

  it('is constructed exactly once however often arm() is called', () => {
    const bus = createCueBus();
    bus.arm();
    bus.arm();
    bus.testSound();
    expect(FakeAudioContext.instances).toHaveLength(1);
  });

  it('is resumed by arm() and again by resume(), because a hidden tab suspends it', () => {
    const bus = createCueBus();
    bus.arm();
    const context = latestContext();
    expect(context.state).toBe('running');
    context.state = 'suspended';
    bus.resume();
    expect(context.state).toBe('running');
  });

  it('is closed on close(), and the bus stays inert rather than reopening', () => {
    const bus = createCueBus();
    bus.arm();
    const context = latestContext();
    bus.close();
    expect(context.closed).toBe(true);
    bus.play('work');
    expect(FakeAudioContext.instances).toHaveLength(1);
  });

  it('survives a constructor that throws — a device at its context limit is not an error', () => {
    vi.stubGlobal(
      'AudioContext',
      class {
        constructor() {
          throw new Error('too many contexts');
        }
      },
    );
    const bus = createCueBus();
    expect(() => {
      bus.arm();
      bus.play('work');
    }).not.toThrow();
    expect(bus.isArmed()).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe('feature detection', () => {
  it('reports no audio when no constructor exists, and every method is a no-op', () => {
    vi.stubGlobal('AudioContext', undefined);
    expect(audioCuesAvailable()).toBe(false);
    const bus = createCueBus();
    expect(bus.audioAvailable).toBe(false);
    expect(() => {
      bus.arm();
      bus.play('rest');
      bus.testSound();
      bus.resume();
      bus.close();
    }).not.toThrow();
    expect(FakeAudioContext.instances).toHaveLength(0);
    vi.unstubAllGlobals();
  });

  it('vibrates alongside the tone, with the cue own pattern', () => {
    const vibrate = vi.spyOn(navigator, 'vibrate').mockReturnValue(true);
    const bus = createCueBus();
    bus.arm();
    bus.play('rest');
    expect(vibrate).toHaveBeenCalledWith([180]);
  });

  it('still vibrates before arm(), because the two channels are independent', () => {
    const vibrate = vi.spyOn(navigator, 'vibrate').mockReturnValue(true);
    const bus = createCueBus();
    bus.play('work');
    expect(vibrate).toHaveBeenCalledWith([80, 60, 80]);
    expect(FakeAudioContext.instances).toHaveLength(0);
  });

  it('is a no-op when navigator.vibrate is absent — iOS Safari has none', () => {
    Object.defineProperty(navigator, 'vibrate', { value: undefined, configurable: true });
    expect(vibrationAvailable()).toBe(false);
    const bus = createCueBus();
    expect(() => {
      bus.arm();
      bus.play('finish');
    }).not.toThrow();
    Object.defineProperty(navigator, 'vibrate', { value: () => true, configurable: true });
  });

  it('swallows a vibration the OS refuses', () => {
    vi.spyOn(navigator, 'vibrate').mockImplementation(() => {
      throw new Error('refused');
    });
    const bus = createCueBus();
    expect(() => {
      bus.play('work');
    }).not.toThrow();
  });
});
