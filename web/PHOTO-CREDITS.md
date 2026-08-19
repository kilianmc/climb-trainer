# Landing photograph credits

The three photographs on the public landing page, with title, creator, licence and the page each
was obtained from. **All three are CC0** (public domain dedication), so attribution is not legally
required — this file exists because a project that cannot say where its assets came from cannot
prove it has the right to use them.

It lives **outside `public/`** on purpose. Anything under `public/` ships in the app and is a
candidate for the service-worker precache, and a provenance record is a repo concern, not a runtime
one — the photographs are CC0, so nothing here has to be served to anyone.
`landingImages.test.ts` asserts `public/landing/` holds nothing but the derivatives, which is what
stops this file drifting back in.

The originals are **not** in this repository (they are 12–22 MB each); see
`web/scripts/gen-landing-images.mjs` for how the derivatives are produced from them, and
`web/src/ui/landingImages.ts` for the width ladder and the crop each is cut to.

| File stem        | Title                                  | Creator                    | Licence | Source                                                     |
| ---------------- | -------------------------------------- | -------------------------- | ------- | ---------------------------------------------------------- |
| `hero-granite`   | `File:Casey climbing (Unsplash).jpg`   | Tommy Lisbin (`tlisbin`)   | CC0     | <https://commons.wikimedia.org/w/index.php?curid=61743541> |
| `chimney-effort` | `File:RightOn Climbing (Unsplash).jpg` | Tommy Lisbin (`tlisbin`)   | CC0     | <https://commons.wikimedia.org/w/index.php?curid=61743679> |
| `rope-detail`    | Climbing Rope                          | Burst (`Burst`), StockSnap | CC0     | <https://stocksnap.io/photo/climbing-rope-JFYETACCUU>      |

## Temporary stand-ins

⚠️ These three fill the landing cards' image frames **only until real app screenshots exist**
(Stage 2). They are photographs of climbing, not of this software, which is why every alt text and
every visible caption says so. They and their derivatives are removed when the screenshots land.

| File stem       | Title                                     | Creator          | Licence | Slot              |
| --------------- | ----------------------------------------- | ---------------- | ------- | ----------------- |
| `shot-gym-wall` | `File:Expert Rock Climber (Unsplash).jpg` | Igor Ovsyannykov | CC0     | plan card, 16:9   |
| `shot-blue-sky` | `File:Man rock climbing (Unsplash).jpg`   | Mars Williams    | CC0     | session card, 1:1 |
| `shot-summit`   | Scaling a mountain peak (Unsplash)        | Kalen Emsley     | CC0     | diary card, 1:1   |

The collection metadata carries no landing URL for these three, so none is recorded rather than one
being guessed. All are CC0.

⚠️ **`rope-detail`'s original is 960 x 640 and no larger version is available** — it is the 960w
thumbnail StockSnap publishes, not the 4460px master its metadata mentions. That is why its ladder
stops at 960 and why the layout slot for it is capped: see the warning in `landingImages.ts`.

`chimney-effort` is cut to **4:5**, not to the original's 3:2: the effort band renders it tall, so
the crop is part of the composition rather than an afterthought. `hero-granite` and `rope-detail`
keep 3:2.
