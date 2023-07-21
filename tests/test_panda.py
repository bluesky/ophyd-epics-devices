"""Test file specifying how we want to eventually interact with the panda..."""
from typing import Dict

import numpy as np
import pytest
from ophyd.v2.core import Device, DeviceCollector, SignalRW, get_device_children

from ophyd_epics_devices.panda import PandA, SeqTable, SeqTrigger


@pytest.fixture
async def sim_panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDAQSRV")

    assert sim_panda.name == "sim_panda"
    yield sim_panda


def test_panda_names_correct(pva, sim_panda: PandA):
    assert sim_panda.seq[1].name == "sim_panda-seq-1"
    assert sim_panda.pulse[1].name == "sim_panda-pulse-1"


async def test_panda_children_connected(pva, sim_panda: PandA):
    # try to set and retrieve from simulated values...
    table = SeqTable(
        repeats=np.array([1, 1, 1, 32]).astype(np.uint16),
        trigger=(
            SeqTrigger.POSA_GT,
            SeqTrigger.POSA_LT,
            SeqTrigger.IMMEDIATE,
            SeqTrigger.IMMEDIATE,
        ),
        position=np.array([3222, -565, 0, 0], dtype=np.int32),
        time1=np.array([5, 0, 10, 10]).astype(np.uint32),  # TODO: change below syntax.
        outa1=np.array([1, 0, 0, 1]).astype(np.bool_),
        outb1=np.array([0, 0, 1, 1]).astype(np.bool_),
        outc1=np.array([0, 1, 1, 0]).astype(np.bool_),
        outd1=np.array([1, 1, 0, 1]).astype(np.bool_),
        oute1=np.array([1, 0, 1, 0]).astype(np.bool_),
        outf1=np.array([1, 0, 0, 0]).astype(np.bool_),
        time2=np.array([0, 10, 10, 11]).astype(np.uint32),
        outa2=np.array([1, 0, 0, 1]).astype(np.bool_),
        outb2=np.array([0, 0, 1, 1]).astype(np.bool_),
        outc2=np.array([0, 1, 1, 0]).astype(np.bool_),
        outd2=np.array([1, 1, 0, 1]).astype(np.bool_),
        oute2=np.array([1, 0, 1, 0]).astype(np.bool_),
        outf2=np.array([1, 0, 0, 0]).astype(np.bool_),
    )
    await sim_panda.pulse[1].delay.set(20.0)
    await sim_panda.seq[1].table.set(table)

    readback_pulse = await sim_panda.pulse[1].delay.get_value()
    readback_seq = await sim_panda.seq[1].table.get_value()

    assert readback_pulse == 20.0
    assert readback_seq == table


async def test_panda_with_missing_blocks(pva):
    panda = PandA("PANDAQSRVI")
    with pytest.raises(AssertionError):
        await panda.connect()


async def test_panda_with_extra_blocks(pva):
    panda = PandA("PANDAQSRV")
    await panda.connect()

    assert panda.extra, "extra device has not been instantiated"  # type: ignore


async def test_panda_block_missing_signals(pva):
    panda = PandA("PANDAQSRVIB")

    with pytest.raises(Exception) as exc:
        await panda.connect()
        assert (
            exc.__str__
            == "PandA has a pulse block containing a width signal which has not been "
            + "retrieved by PVI."
        )


async def test_panda_sort_signal_by_phase(sim_panda: PandA):
    # This function is borrowed from panda.py in ophyd-epics-devices for now
    def find_component_signals(device: Device, prefix: str):
        for attr_name, attr in get_device_children(device):
            dot = ""

            # Place a dot inbetween the uppwer and lower class. Don't do this for highest level class.
            if prefix:
                dot = "."

            dot_path = f"{prefix}{dot}{attr_name}"

            if isinstance(attr, SignalRW):
                signalRWs[dot_path] = attr
            # Need to account for the attr being a dictionary which contains

            find_component_signals(attr, prefix=dot_path)

    signalRWs: Dict[str, SignalRW] = {}
    find_component_signals(sim_panda, "")

    phases = sim_panda.sort_signal_by_phase(signalRWs)
    assert len(phases) == 2
    for phase in phases:
        assert len(phase)
    for signal in phase[0]:
        assert phase.source[:4] == "units"
    for signal in phase[1]:
        assert phase.source[:4] != "units"

    # Check two phases are returned, which are lists of signalRW's. the first of which has everything ending in units and the second does not
    pass


def test_panda_sort_signal_by_phase_throws_error_on_empty_phase():
    pass
