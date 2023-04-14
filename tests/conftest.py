import subprocess
import sys
import time
from pathlib import Path

import pytest

RECORD = str(Path(__file__).parent / "db" / "panda.db")


@pytest.fixture(scope="module", params=["pva", "ca"])
def pva():
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "epicscorelibs.ioc",
            "-d",
            RECORD,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    time.sleep(2)
    assert not process.poll(), process.stdout.read().decode("utf-8")
    yield process

    process.terminate()


# @pytest.fixture(scope="session")
# def pva():
#     process = subprocess.Popen(
#         ["softIocPVA", "-d", "tests/db/panda.db"],
#         stdout=subprocess.PIPE,
#         stderr=subprocess.STDOUT,
#     )
#     time.sleep(2)
#     assert not process.poll(), process.stdout.read().decode("utf-8")
#     yield process

#     process.terminate()
