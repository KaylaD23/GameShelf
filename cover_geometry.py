"""Pixel placement for GameShelf cover art.

GameShelf's default poster mode displays every source pixel across the entire
fixed poster frame. This deliberately allows mild aspect-ratio distortion: a
fixed box cannot simultaneously preserve proportions, avoid cropping, and
avoid letterboxing when the source ratio differs.

The fit_inside and crop_to_fill helpers are retained for callers that explicitly
need them; the default grid/details renderers must not use either.
This file has no GUI dependencies so the geometry can be unit tested anywhere.
"""


def fit_inside(image_width: int, image_height: int, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of a centred, aspect-preserving image.

    Rectangles use integer pixel geometry and always remain inside the frame.
    """
    if min(image_width, image_height, frame_width, frame_height) <= 0:
        raise ValueError('Cover image and frame dimensions must all be positive')
    scale = min(frame_width / image_width, frame_height / image_height)
    width = max(1, min(frame_width, round(image_width * scale)))
    height = max(1, min(frame_height, round(image_height * scale)))
    return (frame_width - width) // 2, (frame_height - height) // 2, width, height


def crop_to_fill(image_width: int, image_height: int, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    """Centred SOURCE rectangle that fills a target without distorting artwork.

    The returned crop is in source-image pixels, so both the details widget and
    the virtualized thumbnail delegate can paint at any resolution/DPI.
    """
    if min(image_width, image_height, frame_width, frame_height) <= 0:
        raise ValueError('Cover image and frame dimensions must all be positive')
    if image_width * frame_height > image_height * frame_width:
        crop_height = image_height
        crop_width = max(1, min(image_width, round(image_height * frame_width / frame_height)))
    else:
        crop_width = image_width
        crop_height = max(1, min(image_height, round(image_width * frame_height / frame_width)))
    return ((image_width - crop_width) // 2, (image_height - crop_height) // 2, crop_width, crop_height)


def crop_retention(image_width: int, image_height: int, frame_width: int, frame_height: int) -> float:
    """How much of the original image survives a full-bleed centre crop."""
    _, _, crop_width, crop_height = crop_to_fill(image_width, image_height, frame_width, frame_height)
    return (crop_width * crop_height) / (image_width * image_height)


# Keep slight aspect-ratio mismatches fully visible instead of shaving off edges.
NEAR_MATCH_RETENTION = 0.965


def should_fit_inside(image_width: int, image_height: int, frame_width: int, frame_height: int, *, retention_threshold: float = NEAR_MATCH_RETENTION) -> bool:
    """Return True when artwork is close enough to show fully without cropping.

    A retention of 96.5% means a full-bleed crop would remove 3.5% or less of
    the artwork area, which is visually more annoying than a tiny letterbox.
    """
    if not 0 < retention_threshold <= 1:
        raise ValueError('retention_threshold must be within 0 < x <= 1')
    if min(image_width, image_height, frame_width, frame_height) <= 0:
        raise ValueError('Cover image and frame dimensions must all be positive')
    return crop_retention(image_width, image_height, frame_width, frame_height) >= retention_threshold


def fitted_size(image_width: int, image_height: int, frame_width: int, frame_height: int) -> tuple[int, int]:
    """Size of a scaled image that fits fully inside the poster frame."""
    _, _, width, height = fit_inside(image_width, image_height, frame_width, frame_height)
    return width, height


def scaled_to_fill(image_width: int, image_height: int, frame_width: int, frame_height: int) -> tuple[int, int]:
    """Size of a decoded thumbnail that fully covers the target, not a huge source."""
    import math
    if min(image_width, image_height, frame_width, frame_height) <= 0:
        raise ValueError('Cover image and frame dimensions must all be positive')
    factor = max(frame_width / image_width, frame_height / image_height)
    return max(frame_width, math.ceil(image_width * factor)), max(frame_height, math.ceil(image_height * factor))


def poster_fit_rect(image_width: int, image_height: int, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    """The one poster policy used everywhere: show 100% of the source image.

    Returned destination rectangle lies entirely within frame, preserves
    original aspect ratio and includes all four source-image edges.
    """
    return fit_inside(image_width, image_height, frame_width, frame_height)


def poster_fill_rect(frame_width: int, frame_height: int) -> tuple[int,int,int,int]:
    """Full poster destination. No bars or missing pixels (nonproportional scaling)."""
    if min(frame_width, frame_height) <= 0:
        raise ValueError('Poster frame dimensions must be positive')
    return (0, 0, frame_width, frame_height)
