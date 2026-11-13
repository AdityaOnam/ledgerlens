from ledgerlens.ingest.cache import ResponseCache, cache_key


def test_key_depends_on_every_part_but_not_on_order():
    a = cache_key(model="m", text="t", prompt=1)
    assert a == cache_key(prompt=1, text="t", model="m")
    assert a != cache_key(model="m2", text="t", prompt=1)
    assert a != cache_key(model="m", text="t ", prompt=1)


def test_round_trip_and_miss(tmp_path):
    cache = ResponseCache(tmp_path / "c")
    key = cache_key(text="hello")
    assert cache.get(key) is None
    cache.put(key, {"agreements": [], "note": "é"})
    assert cache.get(key) == {"agreements": [], "note": "é"}
    assert not list((tmp_path / "c").rglob("*.tmp"))


def test_corrupt_entry_is_a_miss(tmp_path):
    cache = ResponseCache(tmp_path)
    key = cache_key(text="x")
    cache.put(key, {"a": 1})
    next(tmp_path.rglob("*.json")).write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None
