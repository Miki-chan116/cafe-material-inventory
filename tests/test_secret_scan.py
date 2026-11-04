from scripts.scan_secrets import scan_text


def test_dummy_secret_pattern_is_detected_without_using_a_real_secret():
    fake = "ghp_" + "x" * 36
    assert scan_text(fake)
    assert not scan_text("ordinary inventory data")
