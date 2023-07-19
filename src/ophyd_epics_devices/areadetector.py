import asyncio
import tempfile
import time
from abc import abstractmethod
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, Protocol, Sequence, Type

from bluesky.protocols import (
    Asset,
    Collectable,
    Descriptor,
    Flyable,
    Triggerable,
    WritesExternalAssets,
)
from bluesky.utils import new_uid
from event_model import StreamDatum, compose_stream_resource
from ophyd.v2.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    Device,
    SignalR,
    SignalRW,
    StandardReadable,
    T,
    set_and_wait_for_value,
)
from ophyd.v2.epics import epics_signal_r, epics_signal_rw


def ad_rw(datatype: Type[T], prefix: str) -> SignalRW[T]:
    return epics_signal_rw(datatype, prefix + "_RBV", prefix)


def ad_r(datatype: Type[T], prefix: str) -> SignalR[T]:
    return epics_signal_r(datatype, prefix + "_RBV")


class ImageMode(Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class ADDriver(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.acquire = ad_rw(bool, prefix + "Acquire")
        self.acquire_time = ad_rw(float, prefix + "AcquireTime")
        self.num_images = ad_rw(int, prefix + "NumImages")
        self.image_mode = ad_rw(ImageMode, prefix + "ImageMode")
        self.array_counter = ad_rw(int, prefix + "ArrayCounter")
        self.array_size_x = ad_r(int, prefix + "ArraySizeX")
        self.array_size_y = ad_r(int, prefix + "ArraySizeY")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")


class NDPlugin(Device):
    pass


class NDPluginStats(NDPlugin):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.unique_id = ad_r(int, prefix + "UniqueId")


class SingleTriggerDet(StandardReadable, Triggerable):
    def __init__(
        self,
        drv: ADDriver,
        read_uncached: Sequence[SignalR] = (),
        name="",
        **plugins: NDPlugin,
    ) -> None:
        self.drv = drv
        self.__dict__.update(plugins)
        self.set_readable_signals(
            # Can't subscribe to read signals as race between monitor coming back and
            # caput callback on acquire
            read_uncached=[self.drv.array_counter] + list(read_uncached),
            config=[self.drv.acquire_time],
        )
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
        )
        await super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        await self.drv.acquire.set(1)


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class NDFileHDF(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.file_path = ad_rw(str, prefix + "FilePath")
        self.file_name = ad_rw(str, prefix + "FileName")
        self.file_template = ad_rw(str, prefix + "FileTemplate")
        self.full_file_name = ad_r(str, prefix + "FullFileName")
        self.file_write_mode = ad_rw(FileWriteMode, prefix + "FileWriteMode")
        self.num_capture = ad_rw(int, prefix + "NumCapture")
        self.num_captured = ad_r(int, prefix + "NumCaptured")
        self.swmr_mode = ad_rw(bool, prefix + "SWMRMode")
        self.lazy_open = ad_rw(bool, prefix + "LazyOpen")
        self.capture = ad_rw(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.array_size0 = ad_r(int, prefix + "ArraySize0")
        self.array_size1 = ad_r(int, prefix + "ArraySize1")


class _HDFResource:
    def __init__(self, hdf_name: str, full_file_name: str) -> None:
        self._last_emitted = 0
        self._last_flush = time.monotonic()
        self._hdf_name = hdf_name
        self.stream_resource, self._compose_datum = compose_stream_resource(
            spec="AD_HDF5_SWMR_SLICE",
            root="/",
            resource_path=full_file_name,
            resource_kwargs={},
        )

    def stream_datum(self, num_captured: int) -> Optional[StreamDatum]:
        if num_captured > self._last_emitted:
            indices = dict(start=self._last_emitted, stop=num_captured)
            datum_doc = self._compose_datum(
                data_keys=[self._hdf_name],
                indices=indices,
                # Until we support rewind, these will always be the same
                seq_nums=indices,
            )
            self._last_emitted = num_captured
            self._last_flush = time.monotonic()
            return datum_doc
        if time.monotonic() - self._last_flush > FRAME_TIMEOUT:
            raise TimeoutError(
                f"{self._hdf_name}: writing stalled on frame {num_captured}"
            )
        return None


class DirectoryProvider(Protocol):
    @abstractmethod
    async def get_directory(self) -> Path:
        ...


class TmpDirectoryProvider(DirectoryProvider):
    def __init__(self) -> None:
        self._directory = Path(tempfile.mkdtemp())

    async def get_directory(self) -> Path:
        return self._directory


# How long to wait for new frames before timing out
FRAME_TIMEOUT = 120


class HDFStreamerDet(StandardReadable, Flyable, WritesExternalAssets, Collectable):
    def __init__(
        self, drv: ADDriver, hdf: NDFileHDF, dp: DirectoryProvider, name=""
    ) -> None:
        self.drv = drv
        self.hdf = hdf
        self._dp = dp
        self._resource: Optional[_HDFResource] = None
        self._capture_status: Optional[AsyncStatus] = None
        self._start_status: Optional[AsyncStatus] = None
        self.set_readable_signals(config=[self.drv.acquire_time])
        super().__init__(name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        # Mark that we need a new resource
        self._resource = None
        await asyncio.gather(
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            self.hdf.file_path.set(str(await self._dp.get_directory())),
            self.hdf.file_name.set(f"{self.name}-{new_uid()}"),
            self.hdf.file_template.set("%s/%s.h5"),
            # Go forever
            self.hdf.num_capture.set(0),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.hdf.capture, True)
        await super().stage()

    async def describe(self) -> Dict[str, Descriptor]:
        datakeys = await super().describe()
        # Insert a descriptor for the HDF resource, this will not appear
        # in read() as it describes StreamResource outputs only
        datakeys[self.name] = Descriptor(
            source=self.hdf.full_file_name.source,
            shape=await asyncio.gather(
                self.drv.array_size_y.get_value(),
                self.drv.array_size_x.get_value(),
            ),
            dtype="array",
            external="STREAM:",
        )
        return datakeys

    # For step scan, take a single frame
    @AsyncStatus.wrap
    async def trigger(self):
        await self.drv.image_mode.set(ImageMode.single)
        frame_timeout = DEFAULT_TIMEOUT + await self.drv.acquire_time.get_value()
        await self.drv.acquire.set(1, timeout=frame_timeout)

    async def collect_asset_docs(self) -> AsyncIterator[Asset]:
        num_captured = await self.hdf.num_captured.get_value()
        if num_captured:
            # As soon as HDF writer writes the first frame, full_file_name is valid
            # so can emit the resource
            if self._resource is None:
                self._resource = _HDFResource(
                    hdf_name=self.name,
                    full_file_name=await self.hdf.full_file_name.get_value(),
                )
                yield ("stream_resource", self._resource.stream_resource)
            # If more frames written than last time, emit a datum for it and flush
            stream_datum = self._resource.stream_datum(num_captured)
            if stream_datum:
                await self.hdf.flush_now.set(1)
                yield ("stream_datum", stream_datum)

    # Same describe as for step scans
    describe_collect = describe

    # For flyscan, take the number of frames we wanted
    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        await self.drv.image_mode.set(ImageMode.multiple)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._start_status = await set_and_wait_for_value(self.drv.acquire, True)

    @AsyncStatus.wrap
    async def complete(self) -> None:
        assert self._start_status, "Kickoff not run"
        await self._start_status

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        assert self._capture_status, "Stage not run"
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        await self._capture_status
        await super().unstage()
