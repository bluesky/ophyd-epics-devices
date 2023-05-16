from bluesky import RunEngine

# these three lines just let you use await statements
# #in ipython terminal with the Run Engine event loop.
from IPython import get_ipython
from ophyd.v2.core import DeviceCollector

from ophyd_epics_devices.panda import PandA

get_ipython().run_line_magic("autoawait", "call_in_bluesky_event_loop")
RE = RunEngine()

with DeviceCollector():
    my_panda = PandA("TS-PANDA")
