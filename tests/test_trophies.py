"""Tests for scripts/trophies.py with a fake Commons client (no network). Run: python3 tests/test_trophies.py"""
import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import trophies as T  # noqa: E402


class FakeCommons:
    """Search results and file info shaped like the real API's."""
    def __init__(self, results, files):
        self.results, self.files, self.ua, self.delay = results, files, "test", 0

    def search(self, query, limit=20):
        return self.results.get(query, [])

    def info(self, titles, width=500):
        return {t: self.files[t] for t in titles if t in self.files}


def f(licence, width=1200, mime="image/jpeg", author="Some Photographer", size=3_000_000):
    return {"url": "https://upload.example/a/ab/X.jpg", "thumb": "https://upload.example/thumb/a/ab/X.jpg/500px-X.jpg",
            "page": "https://commons.example/File", "mime": mime, "width": width, "bytes": size,
            "licence": licence, "licence_url": "https://creativecommons.org/", "author": author}


def test_licences():
    assert T.free_licence("CC BY-SA 4.0") and T.free_licence("CC BY 2.0") and T.free_licence("CC0") and T.free_licence("Public domain")
    assert not T.free_licence("CC BY-NC-SA 2.0") and not T.free_licence("CC BY-ND 3.0") and not T.free_licence("") and not T.free_licence("All rights reserved")


def test_score_on_real_search_results():
    # file names the first automatic run picked (Oct 2026): only the first three are tennis trophies
    good = [("Roland Garros", "File:Coupe des Mousquetaires (cropped).jpg"),
            ("Wimbledon", "File:Gentlemen's Singles Trophy Wimbledon 2023.jpg"),
            ("Madrid Masters", "File:Trofeo Masters de Madrid - 01.jpg")]
    bad = [("Australian Open", "File:Australian Championship trophy at Lakeside.jpg"),
           ("US Open", "File:Tan Aik Huang receiving the men's singles trophy at the 1966 U.S. Open.jpg"),
           ("ATP Finals", "File:2014-11-12 2014 ATP World Tour Finals Borna Coric receiving trophy for ATP Star of tomorrow 2014 1 by Michael Frey.jpg"),
           ("Shanghai", "File:Exhibition of war trophies from Shanghai Incident at the Japanese Army Ministry.jpg"),
           ("Hamburg", "File:Finale Europa Cup II AC Milan tegen HSV Hamburg 2-0. Aanvoerder Gianni Rivera me, Bestanddeelnr 921-3773.jpg"),
           ("Auckland", "File:Hydrangea macrophylla 'Trophy' in Auckland Botanic Gardens.jpg"),
           ("Monte Carlo", "File:Remise de la Coupe des Dames 1939 du rallye Monte-Carlo à Mmes Simon (G.) et Largeot (D.).jpg"),
           ("Basel", "File:Next Generation Trophy 2012 Athletic Bilbao FC Basel 2.JPG"),
           ("Dallas", "File:Dallas Fuel players holding 2022 OWL Grand Finals trophy - 2.jpg"),
           ("Wimbledon", "File:Venus Rosewater Dish.jpg"),
           ("Roland Garros", "File:Coupe Suzanne Lenglen Roland Garros.jpg")]
    for name, title in good:
        assert T.score(title, name) is not None, title
    for name, title in bad:
        assert T.score(title, name) is None, title


def test_find_lists_free_candidates_only():
    client = FakeCommons(
        {"Wimbledon gentlemen's singles trophy": ["File:Wimbledon trophy small.jpg", "File:Wimbledon trophy NC.jpg",
                                                  "File:Gentlemen's Singles Trophy Wimbledon 2023.jpg"]},
        {"File:Wimbledon trophy small.jpg": f("CC BY-SA 4.0", width=200), "File:Wimbledon trophy NC.jpg": f("CC BY-NC 2.0"),
         "File:Gentlemen's Singles Trophy Wimbledon 2023.jpg": f("CC BY 2.0")})
    out = T.find(client, [{"key": "540", "name": "Wimbledon"}, {"key": "999", "name": "Nowhere"}])
    assert [c["file"] for c in out["540"]["candidates"]] == ["File:Gentlemen's Singles Trophy Wimbledon 2023.jpg"]
    assert out["999"]["candidates"] == []


def test_thumb_sizes_to_try():
    urls = T.thumb_urls(f("CC BY 2.0", size=900_000))
    assert urls[0].endswith("/500px-X.jpg") and urls[1].endswith("/330px-X.jpg") and urls[2].endswith("/250px-X.jpg")
    assert urls[-1] == "https://upload.example/a/ab/X.jpg"            # small original as a last resort
    assert "https://upload.example/a/ab/X.jpg" not in T.thumb_urls(f("CC BY 2.0", size=9_000_000))


def test_build_falls_back_on_403_and_keeps_going():
    client = FakeCommons({}, {"File:A.jpg": f("CC BY-SA 3.0", author="Jane Doe"), "File:B.jpg": f("CC BY-NC 2.0"),
                              "File:C.jpg": f("CC BY 2.0")})
    tried = []

    def fetch(url, dest):
        tried.append(url)
        if "/500px-" in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with open(dest, "wb") as fh:
            fh.write(b"\xff\xd8fakejpeg")
    with tempfile.TemporaryDirectory() as tmp:
        cache, out = os.path.join(tmp, "cache"), os.path.join(tmp, "out")
        credits = T.build(client, {"580": {"file": "File:A.jpg"}, "520": {"file": "File:B.jpg"}, "1": {"file": None}}, cache, out, fetch)
        assert list(credits) == ["580"] and credits["580"]["author"] == "Jane Doe"
        assert any("/330px-" in u for u in tried)                         # 500 px refused, 330 px used
        assert os.path.exists(os.path.join(out, credits["580"]["src"]))
        n = len(tried)
        T.build(client, {"580": {"file": "File:A.jpg"}}, cache, out, fetch)  # cached: no download
        assert len(tried) == n

        def always_403(url, dest):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        credits = T.build(client, {"9": {"file": "File:C.jpg"}, "580": {"file": "File:A.jpg"}}, cache, out, always_403)
        assert list(credits) == ["580"]                                    # one failure does not stop the others


def test_pinned_list_is_valid():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "trophies.json")
    with open(path, encoding="utf-8") as fh:
        pins = json.load(fh)
    assert pins and all(v["file"].startswith("File:") and T.score(v["file"], v["name"]) is not None for v in pins.values())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("pass", name)
