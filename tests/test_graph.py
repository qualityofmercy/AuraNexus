from auranexus.tools import graph


def test_waves_and_critical_path():
    r = graph.analyse(["a", "b", "c", "d"], [("a", "c"), ("b", "c"), ("c", "d")], {"a": 5, "b": 1, "c": 2, "d": 1})
    assert r.waves == [["a", "b"], ["c"], ["d"]]
    assert r.critical_path == ["a", "c", "d"]
    assert r.critical_length == 8
    assert not r.cycles


def test_cycle_is_reported_and_excluded():
    r = graph.analyse(["a", "b", "c"], [("a", "b"), ("b", "a")])
    assert r.cycles == [["a", "b"]]
    assert r.waves == [["c"]]


def test_missing_prerequisite_reported():
    r = graph.analyse(["a"], [("ghost", "a")])
    assert r.missing_prerequisites == [("a", "ghost")]
    assert r.waves == [["a"]]


def test_downstream_fan_out():
    assert graph.downstream("a", [("a", "b"), ("b", "c"), ("x", "y")]) == {"b", "c"}
