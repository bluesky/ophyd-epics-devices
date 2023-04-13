import pytest
import subprocess
import time


@pytest.fixture(scope="session")
def pva():
    process = subprocess.Popen(
        ["softIocPVA", "-d", "tests/db/panda.db"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)
    assert not process.poll(), process.stdout.read().decode("utf-8")
    yield process

    process.terminate()
