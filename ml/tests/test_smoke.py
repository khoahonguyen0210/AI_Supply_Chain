import scm_common


def test_shared_package_importable() -> None:
    assert scm_common.__version__ == "0.1.0"
