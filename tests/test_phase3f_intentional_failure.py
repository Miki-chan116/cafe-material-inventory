"""Disposable CI gate experiment; never merge this branch."""


def test_phase3f_intentional_failure():
    assert False, "Intentional failure for branch protection verification"
