from typing import get_type_hints

from ophyd_epics_devices.utils import get_type_hints_no_inheritance


def test_get_type_hints_no_inheritance():
    class BaseClass:
        base_integer: int
        base_string: str

    class SubClass(BaseClass):
        integer: int
        string: str

    assert get_type_hints(SubClass) == {
        "base_integer": int,
        "base_string": str,
        "integer": int,
        "string": str,
    }
    assert get_type_hints_no_inheritance(SubClass) == {"integer": int, "string": str}
