import { publicUrl } from '../publicUrl';
import { LANDING_FORMATS, landingFile, landingHeight, type LandingImage } from './landingImages';

/**
 * One landing photograph as a `<picture>`: AVIF, then WebP, then a JPEG `<img>` fallback.
 *
 * Source order is significance order — the browser takes the first `<source>` whose `type` it
 * supports, so AVIF must come first or it is never used. The `<img>` is not a fourth option, it
 * is the element that actually renders; its `srcset` is the ladder for a browser that reads
 * `srcset` but neither modern format.
 *
 * `width`/`height` are derived from the declared aspect rather than written by hand, and they are
 * what reserves the box before the first byte arrives. Where the CSS also sets an `aspect-ratio`
 * (the bands crop to 16:9 and 21:9), the CSS wins — but the attributes still make the intrinsic
 * ratio right for any context that has no stylesheet yet.
 */
export interface LandingPictureProps {
  image: LandingImage;
  className?: string;
  /**
   * The `sizes` hint. See the note in `Marketing.tsx` about the one `100vw` on this page: `sizes`
   * is resource selection, not layout, so a viewport-relative hint can only over-request in the
   * federated mount — it can never move a box.
   */
  sizes: string;
  /**
   * The hero, and only the hero. Sets `fetchpriority="high"` + eager + synchronous decode, which
   * is worth having exactly once per page: applied to a second image it just competes with the
   * first. Everything else is `loading="lazy"`.
   */
  priority?: boolean;
}

function srcset(image: LandingImage, extension: string, widths: readonly number[]): string {
  return widths.map((w) => `${publicUrl(landingFile(image, w, extension))} ${w}w`).join(', ');
}

export function LandingPicture({ image, className, sizes, priority = false }: LandingPictureProps) {
  return (
    <picture>
      {LANDING_FORMATS.map(({ extension, mime }) => (
        <source
          key={extension}
          type={mime}
          srcSet={srcset(image, extension, image.widths)}
          sizes={sizes}
        />
      ))}
      <img
        className={className}
        src={publicUrl(landingFile(image, image.fallbackWidth, 'jpg'))}
        srcSet={srcset(image, 'jpg', image.fallbackWidths)}
        sizes={sizes}
        alt={image.alt}
        width={image.fallbackWidth}
        height={landingHeight(image, image.fallbackWidth)}
        loading={priority ? 'eager' : 'lazy'}
        fetchPriority={priority ? 'high' : 'auto'}
        decoding={priority ? 'sync' : 'async'}
      />
    </picture>
  );
}
