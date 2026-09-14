import { readFileSync } from 'node:fs';
import { cwd } from 'node:process';

import { describe, expect, it } from 'vitest';

import { INTENSITY_ANCHORS } from './intensity';

/* Driven off the GENERATED schema, never a list restated here: nine hard-coded kinds would
   agree with `intensity.ts` by construction. The synthetic arm proves the detector sees. */
const SCHEMA = `${cwd()}/src/api/schema.ts`;

/** The union members of `ProtocolKind`, as `schema.ts` spells them. */
export function protocolKindsIn(source: string): string[] {
  const body = /ProtocolKind:([\s\S]*?);/.exec(source)?.[1];
  if (body === undefined) throw new Error('schema.ts declares no ProtocolKind');
  return [...body.matchAll(/'([a-z_]+)'/g)].flatMap((match) => match[1] ?? []);
}

/** Kinds the anchor map cannot answer for — empty string included, which says nothing. */
function withoutAnchor(kinds: readonly string[]): string[] {
  const anchors: Record<string, string | undefined> = INTENSITY_ANCHORS;
  return kinds.filter((kind) => {
    const anchor = anchors[kind];
    return anchor === undefined || anchor.trim() === '';
  });
}

describe('the intensity anchor', () => {
  const kinds = protocolKindsIn(readFileSync(SCHEMA, 'utf8'));

  it('answers for every protocol kind the schema declares', () => {
    expect(withoutAnchor(kinds)).toEqual([]);
  });

  it('reads a real union rather than passing on an empty match', () => {
    expect(kinds).toContain('max_hang');
    expect(kinds).toContain('other');
    expect(kinds.length).toBeGreaterThanOrEqual(9);
  });

  it('names no kind the schema does not have', () => {
    expect(Object.keys(INTENSITY_ANCHORS).filter((kind) => !kinds.includes(kind))).toEqual([]);
  });

  it('would go red on a kind added without an anchor', () => {
    const synthetic = "ProtocolKind:\n | 'max_hang'\n | 'brand_new_kind';";

    expect(protocolKindsIn(synthetic)).toEqual(['max_hang', 'brand_new_kind']);
    expect(withoutAnchor(protocolKindsIn(synthetic))).toEqual(['brand_new_kind']);
  });
});
