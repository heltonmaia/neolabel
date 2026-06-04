"""Video rotation — coordinate transform + endpoint."""
from app.services.video import rotate_keypoints


def test_rotate_90_clockwise_maps_point_and_swaps_dims():
    # point (10, 20) in a 100w x 200h image
    kps = [[10, 20, 2]]
    new_kps, w, h = rotate_keypoints(kps, 100, 200, 90)
    assert new_kps == [[180, 10, 2]]  # x'=h-y=180, y'=x=10
    assert (w, h) == (200, 100)


def test_rotate_270_counter_clockwise():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 270)
    assert new_kps == [[20, 90, 2]]  # x'=y=20, y'=w-x=90
    assert (w, h) == (200, 100)


def test_rotate_180_keeps_dims():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 180)
    assert new_kps == [[90, 180, 2]]  # x'=w-x=90, y'=h-y=180
    assert (w, h) == (100, 200)


def test_unset_keypoints_are_untouched():
    # v == 0 means "unset" ([0,0,0]); must not be moved.
    new_kps, _, _ = rotate_keypoints([[0, 0, 0], [10, 20, 2]], 100, 200, 90)
    assert new_kps[0] == [0, 0, 0]


def test_four_90_rotations_return_original_square():
    kps = [[100, 50, 2], [600, 10, 1]]
    cur, w, h = kps, 640, 640
    for _ in range(4):
        cur, w, h = rotate_keypoints(cur, w, h, 90)
    assert cur == kps
    assert (w, h) == (640, 640)
