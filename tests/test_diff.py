import numpy as np

from previously_on.diff import RegionWatcher, has_text_like_content
from previously_on.regions import Region

R = Region("r", 0, 0, 1, 1)


def flat(v):
    return np.full((90, 160, 3), v, np.uint8)


def with_text(v=30):
    img = flat(v)
    img[40:50, 30:130] = 240  # a bright bar where text would be
    return img


def test_no_fire_on_static_frames():
    w = RegionWatcher(R)
    for _ in range(10):
        assert not w.update(flat(30)).fired


def test_fires_once_after_change_settles():
    w = RegionWatcher(R)
    w.update(flat(30))
    fired = [w.update(with_text()).fired for _ in range(5)]
    assert fired == [False, True, False, False, False]


def test_refires_on_next_change():
    w = RegionWatcher(R)
    w.update(flat(30))
    w.update(with_text())
    assert w.update(with_text()).fired
    w.update(flat(30))  # banner gone
    assert w.update(flat(30)).fired  # the watcher fires; the pipeline's text gate drops blanks
    w.update(with_text(40))
    assert w.update(with_text(40)).fired


def test_settle_frames_waits_through_fade_in():
    w = RegionWatcher(R, settle_frames=2)
    w.update(flat(30))
    assert not w.update(with_text()).fired
    assert not w.update(with_text()).fired
    assert w.update(with_text()).fired


def test_text_gate():
    assert not has_text_like_content(flat(30))  # nothing bright
    assert not has_text_like_content(flat(250))  # everything bright
    assert has_text_like_content(with_text())


def fading(step):
    """A bar that brightens gradually: no single frame step is large."""
    img = flat(30)
    img[40:50, 30:130] = min(255, 100 + step * 30)
    return img


def test_slow_fade_in_still_fires():
    w = RegionWatcher(R, max_wait=2)
    w.update(flat(30))
    fired = [w.update(fading(i)).fired for i in range(6)]
    assert any(fired), fired
