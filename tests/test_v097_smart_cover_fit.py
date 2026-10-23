"""v0.9.7 smart cover fit regressions."""

from cover_geometry import crop_retention, fit_inside, should_fit_inside


def test_crash_bandicoot_style_cover_keeps_full_art():
    # Slightly narrower than the poster frame; should not lose its top logo.
    image=(214,300)
    frame=(173,235)
    assert crop_retention(*image,*frame) >= 0.965
    assert should_fit_inside(*image,*frame)
    assert fit_inside(*image,*frame) == (2,0,168,235)


def test_square_cover_still_uses_full_bleed_crop_rule():
    image=(300,300)
    frame=(173,235)
    assert crop_retention(*image,*frame) < 0.9
    assert not should_fit_inside(*image,*frame)
