import { createHash } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import { stdin } from 'node:process';
import { fileURLToPath } from 'node:url';

import openapiTS, { astToString } from 'openapi-typescript';
import { format, resolveConfig } from 'prettier';

/**
 * Turn the API's OpenAPI document into `src/api/schema.ts`.
 *
 * Run it through the root script, never directly:
 *
 *     npm run codegen:api      # uv run python -m server.openapi_schema | node this
 *
 * **An authoring tool, exactly like `gen-landing-images.mjs`, and it must never enter
 * `build`.** The `web` CI job and Vercel's SPA build have Node and no Python, so the
 * output is COMMITTED — the same reasoning that keeps `src/routeTree.gen.ts` in the tree.
 *
 * ## TWO digests, because one of them only proves half of it
 *
 * `server/openapi_schema.py` prints one canonical serialisation; this reads it whole and
 * writes two hashes into the generated header:
 *
 * - **`openapi-sha256`** — the raw stdin bytes, i.e. the INPUT. It catches "somebody
 *   changed an endpoint and did not regenerate".
 * - **`types-sha256`** — the generated body below the header, i.e. the OUTPUT. It catches
 *   a hand-edit. Without it, changing `sessions_per_week: number` to `number | null` in
 *   the committed file left every check green and the client believing a nullability the
 *   API does not have: "do not edit" was a convention, not a guard.
 *
 * `tests/test_vocabulary_contract.py` recomputes both — the first from the live
 * application, the second from the file itself — so both failures land in `pytest`, in the
 * local gate, with no Node and no network. Piping rather than passing a path is what keeps
 * a second generated artifact out of the repository.
 *
 * The output is formatted with Prettier before it is written, so `format:check` stays
 * meaningful over `src/` instead of needing an ignore entry for this file.
 */

const OUTPUT = fileURLToPath(new URL('../src/api/schema.ts', import.meta.url));

/** stdin, whole. The digest has to be of the bytes Python printed, not of a re-encoding. */
async function readStdin() {
  const chunks = [];
  for await (const chunk of stdin) chunks.push(chunk);
  if (chunks.length === 0) {
    throw new Error(
      'no OpenAPI document on stdin. Run `npm run codegen:api` from the repo root, ' +
        'which pipes `uv run python -m server.openapi_schema` into this script.',
    );
  }
  return Buffer.concat(chunks);
}

const raw = await readStdin();
const fingerprint = createHash('sha256').update(raw).digest('hex');
const document = JSON.parse(raw.toString('utf8'));

const body = astToString(await openapiTS(document));
// `resolveConfig` explicitly: `format()` does NOT read `.prettierrc.json` on its own, so
// without this the output keeps the generator's double quotes and 80-column wrapping and
// `format:check` fails on a file nobody is allowed to edit.
const formatted = await format(body, {
  ...(await resolveConfig(OUTPUT)),
  filepath: OUTPUT,
});

const typesDigest = createHash('sha256').update(formatted, 'utf8').digest('hex');

const header = `/**
 * GENERATED FILE — do not edit by hand.
 *
 * \`npm run codegen:api\` (repo root) regenerates it from the FastAPI application:
 * \`server/openapi_schema.py\` prints the OpenAPI document and
 * \`web/scripts/gen-api-types.mjs\` turns it into these types.
 *
 * \`tests/test_vocabulary_contract.py\` checks BOTH digests below, so this file can
 * neither fall behind the server nor be edited by hand without failing the gate:
 *
 *   openapi-sha256  the OpenAPI document it was generated from
 *   types-sha256    everything below this comment block
 *
 * openapi-sha256: ${fingerprint}
 * types-sha256: ${typesDigest}
 */

`;

writeFileSync(OUTPUT, header + formatted, 'utf8');
console.log(`wrote ${OUTPUT}\nopenapi-sha256: ${fingerprint}\ntypes-sha256: ${typesDigest}`);
