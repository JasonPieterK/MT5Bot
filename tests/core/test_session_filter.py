import core.session_filter as session_filter


def test_normal_range_inside():
    assert session_filter.in_session(10, 8, 17) is True


def test_normal_range_outside():
    assert session_filter.in_session(20, 8, 17) is False


def test_wraparound_range_inside_late():
    assert session_filter.in_session(23, 22, 4) is True


def test_wraparound_range_inside_early():
    assert session_filter.in_session(2, 22, 4) is True


def test_wraparound_range_outside():
    assert session_filter.in_session(12, 22, 4) is False


def test_boundary_inclusive():
    assert session_filter.in_session(8, 8, 17) is True
    assert session_filter.in_session(17, 8, 17) is True
