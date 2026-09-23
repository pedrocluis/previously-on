import pytest

from previously_on.games import get_profile


@pytest.fixture(scope="session")
def eldenring():
    return get_profile("eldenring")


@pytest.fixture(scope="session")
def ocr():
    from previously_on.ocr import get_ocr

    return get_ocr()
