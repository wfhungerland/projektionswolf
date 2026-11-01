import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _cwd():
    old = os.getcwd()
    os.chdir(ROOT)
    yield
    os.chdir(old)
