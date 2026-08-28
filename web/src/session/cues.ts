import { useSyncExternalStore } from 'react';

import type { PhaseKind } from './protocol';

/**
 * The cue bus: synthesized tones and a vibration alongside, and nothing that can fail loudly.
 *
 * ⚠️ **Audio is an ENHANCEMENT, never load-bearing.** The primary cue channel is visual — the
 * full-bleed phase colour and the huge countdown — because a muted phone across the room still
 * has to work. Every method here is a no-op when the API is missing, and no caller branches on
 * whether a cue was heard.
 *
 * ⚠️ **`AudioContext` is constructed inside the Start click gesture** (`arm()`), never at module
 * load and never in an effect: one created outside a user gesture starts `suspended` and, on
 * iOS, never resumes. `resume()` is called again on every `visibilitychange`, because returning
 * to a backgrounded tab lands with the context suspended.
 *
 * ⚠️ **The iOS hardware silent switch mutes Web Audio with no workaround** — no API reports it
 * and no unlock trick defeats it. Hence `testSound()`, which the player's mute toggle calls on
 * the way ON: the climber hears what they just enabled, or discovers the silent switch, in the
 * same press. There is no separate "Test sound" button — a control that only ever proves a
 * negative is one nobody presses twice.
 */

/**
 * Three cues, and deliberately only three — the screen already says which phase, which set and
 * how long is left, so a tone only has to answer "pull now / stop now / that's the session".
 * A larger vocabulary is one a climber would have to learn, and it would be learned wrong.
 *
 * - `work` — two short 880 Hz pips. Rising and urgent; the one cue you must not miss.
 * - `rest` — one 440 Hz tone, an octave down and longer. Settled, unmistakably not `work`.
 * - `finish` — 660/550/440 descending. A falling shape reads as an ending in every culture
 *   that has a doorbell, and it can only ever fire once.
 */
export type CueName = 'work' | 'rest' | 'finish';

/** `prepare` and `rest` both mean "don't pull"; `work` and `open` both mean "go". `null` is the
 * end of the timeline. That collapse is why three cues cover four phase kinds. */
export function cueForPhase(kind: PhaseKind | null): CueName {
  if (kind === null) return 'finish';
  return kind === 'work' || kind === 'open' ? 'work' : 'rest';
}

interface Tone {
  /** Hz. */
  readonly hz: number;
  /** Offset from the start of the cue, ms. */
  readonly at: number;
  readonly ms: number;
}

const TONES: Record<CueName, readonly Tone[]> = {
  work: [
    { hz: 880, at: 0, ms: 90 },
    { hz: 880, at: 140, ms: 90 },
  ],
  rest: [{ hz: 440, at: 0, ms: 220 }],
  finish: [
    { hz: 660, at: 0, ms: 160 },
    { hz: 550, at: 200, ms: 160 },
    { hz: 440, at: 400, ms: 320 },
  ],
};

/** The same three shapes in the other channel. Android only; iOS Safari has no `vibrate`. */
const PATTERNS: Record<CueName, readonly number[]> = {
  work: [80, 60, 80],
  rest: [180],
  finish: [120, 80, 120, 80, 240],
};

/** Well under 1.0: these play through a phone speaker at arm's length, not through monitors. */
const PEAK_GAIN = 0.18;
/** A square-edged gain step is an audible click, which reads as a fault rather than a cue. */
const RAMP_SECONDS = 0.012;

type AudioContextCtor = new () => AudioContext;

/** `webkitAudioContext` is still the only constructor on older iOS WebViews. */
function audioContextCtor(): AudioContextCtor | null {
  if (typeof window === 'undefined') return null;
  const scope = window as unknown as {
    AudioContext?: AudioContextCtor;
    webkitAudioContext?: AudioContextCtor;
  };
  return scope.AudioContext ?? scope.webkitAudioContext ?? null;
}

/** Whether a tone could ever be produced. Feature detection only — it says nothing about
 * whether the phone is muted, which no browser API will tell you. */
export function audioCuesAvailable(): boolean {
  return audioContextCtor() !== null;
}

export function vibrationAvailable(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function';
}

/**
 * The mute preference, `ct:`-namespaced like every other key this app writes — in the federated
 * mount `localStorage` belongs to kilianmc.com. Same shape as `theme.ts` and `wakeLock.ts`: a
 * module value, a listener set and `useSyncExternalStore`, because it is external state read
 * during render.
 *
 * ⚠️ **It gates BOTH channels, and that is deliberate rather than sloppy.** A vibration is the
 * same cue in the other channel, and "make it stop going off at me" is one request, not two —
 * a phone that keeps buzzing through a muted session is the complaint the toggle exists to
 * answer. Absent means ON: a climber who has never touched it gets the cues the player is for.
 */
export const SOUND_STORAGE_KEY = 'ct:sound';

function readSoundOn(): boolean {
  try {
    return window.localStorage.getItem(SOUND_STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

let soundOn = typeof window === 'undefined' ? true : readSoundOn();
const soundListeners = new Set<() => void>();

export function getSoundOn(): boolean {
  return soundOn;
}

export function setSoundOn(next: boolean): void {
  soundOn = next;
  try {
    window.localStorage.setItem(SOUND_STORAGE_KEY, next ? 'on' : 'off');
  } catch {
    // A blocked or full store costs the preference its persistence, never this session's cues.
  }
  for (const listener of soundListeners) listener();
}

export function useSoundOn(): boolean {
  return useSyncExternalStore(
    (onChange: () => void) => {
      soundListeners.add(onChange);
      return () => {
        soundListeners.delete(onChange);
      };
    },
    getSoundOn,
    getSoundOn,
  );
}

function playTone(context: AudioContext, tone: Tone): void {
  const start = context.currentTime + tone.at / 1000;
  const end = start + tone.ms / 1000;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.value = tone.hz;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(PEAK_GAIN, start + RAMP_SECONDS);
  gain.gain.setValueAtTime(PEAK_GAIN, Math.max(start + RAMP_SECONDS, end - RAMP_SECONDS));
  gain.gain.linearRampToValueAtTime(0, end);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(start);
  oscillator.stop(end + RAMP_SECONDS);
}

export interface CueBus {
  /** `true` when a tone could be produced at all. Drives nothing but the "Test sound" control. */
  readonly audioAvailable: boolean;
  /** Whether the vibration channel exists. Android only. */
  readonly vibrationAvailable: boolean;
  /** ⚠️ **Call this synchronously inside the Start click handler**, and nowhere else. */
  arm: () => void;
  /** Whether `arm()` got a context. `false` is a normal outcome, not an error. */
  isArmed: () => boolean;
  /** One cue, both channels, best effort. Silent before `arm()`; the vibration still fires.
   *  A no-op in both channels while the mute preference is off — see `SOUND_STORAGE_KEY`. */
  play: (cue: CueName) => void;
  /** The iOS silent-switch affordance: arm from the click, then play `work`. */
  testSound: () => void;
  /** On every `visibilitychange` → visible. A backgrounded context comes back suspended. */
  resume: () => void;
  /** On unmount. Frees the audio hardware; the bus is inert afterwards. */
  close: () => void;
}

/**
 * One bus per player. Holds at most one `AudioContext`, created lazily by `arm()`.
 *
 * Nothing here throws: an `AudioContext` constructor can reject on a device at its context
 * limit, `resume()` rejects without a gesture, and a cue that does not sound is not a failure
 * the climber needs told about — the screen already changed colour.
 */
export function createCueBus(): CueBus {
  let context: AudioContext | null = null;

  const resume = (): void => {
    if (context === null || context.state === 'closed') return;
    if (context.state !== 'suspended') return;
    void context.resume().catch(() => undefined);
  };

  const arm = (): void => {
    if (context !== null) return;
    const Ctor = audioContextCtor();
    if (Ctor === null) return;
    try {
      context = new Ctor();
    } catch {
      context = null;
      return;
    }
    resume();
  };

  const vibrate = (cue: CueName): void => {
    if (!vibrationAvailable()) return;
    try {
      navigator.vibrate([...PATTERNS[cue]]);
    } catch {
      // A vibration refused by OS policy is not something a climber needs told about.
    }
  };

  const play = (cue: CueName): void => {
    if (!soundOn) return;
    vibrate(cue);
    if (context === null || context.state === 'closed') return;
    resume();
    try {
      for (const tone of TONES[cue]) playTone(context, tone);
    } catch {
      // A tone that will not schedule costs this cue, never the phase change behind it.
    }
  };

  return {
    audioAvailable: audioCuesAvailable(),
    vibrationAvailable: vibrationAvailable(),
    arm,
    isArmed: () => context !== null,
    play,
    testSound: () => {
      arm();
      play('work');
    },
    resume,
    close: () => {
      const closing = context;
      context = null;
      if (closing === null || closing.state === 'closed') return;
      void closing.close().catch(() => undefined);
    },
  };
}
