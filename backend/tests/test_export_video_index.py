import csv
import io
import zipfile


def test_frame_ref():
    from app.services.item import _frame_ref

    assert _frame_ref(
        {"image_url": "/files/projects/1/frames/v/f_000003.jpg", "source_video": "v"}
    ) == ("v", "f_000003")
    # image_url present but no source_video -> empty bucket
    assert _frame_ref({"image_url": "/files/x/y/f_000001.jpg"}) == ("", "f_000001")
    # no frame referenced
    assert _frame_ref({"source_video": "v"}) is None
    assert _frame_ref({}) is None


def test_video_index_csv_numeric():
    from app.services.item import build_video_index_csv

    pairs = [
        ("vid_a", "f_000000"),
        ("vid_a", "f_000002"),
        ("vid_b", "f_000005"),
        ("vid_a", "f_000001"),
    ]
    rows = list(csv.DictReader(io.StringIO(build_video_index_csv(pairs))))
    # order = first appearance; first/last numeric; count = frames present
    assert rows[0] == {
        "source_video": "vid_a",
        "first_frame": "0",
        "last_frame": "2",
        "num_frames": "3",
    }
    assert rows[1] == {
        "source_video": "vid_b",
        "first_frame": "5",
        "last_frame": "5",
        "num_frames": "1",
    }


def test_video_index_csv_fallback_and_empty_bucket():
    from app.services.item import build_video_index_csv

    # non-"f_<digits>" stems fall back to the raw stem (lexicographic)
    rows = list(csv.DictReader(io.StringIO(build_video_index_csv([("", "img_7"), ("", "img_3")]))))
    assert rows[0]["source_video"] == ""
    assert rows[0]["first_frame"] == "img_3"
    assert rows[0]["last_frame"] == "img_7"
    assert rows[0]["num_frames"] == "2"


def test_zip_bytes_roundtrip():
    from app.services.item import zip_bytes

    stream, size = zip_bytes([("a.txt", b"hello"), ("b.csv", b"x,y\n")])
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    assert zf.read("a.txt") == b"hello"
    assert zf.read("b.csv") == b"x,y\n"
    assert size > 0
