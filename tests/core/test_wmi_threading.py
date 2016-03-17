# stdlib
import gc
import threading
import time

# 3p
from win32com.client import Dispatch
import pythoncom


def connect_and_query():
    """
    Create a new WMI connection, query and return.
    """
    pythoncom.CoInitialize()
    locator = Dispatch("WbemScripting.SWbemLocator")
    connection = locator.ConnectServer("localhost", "root\\cimv2", "", "")

    # Flags
    flag_return_immediately = 0x10
    flag_forward_only = 0x20

    query_flags = flag_return_immediately | flag_forward_only

    # WQL query
    wql = "Select AvgDiskBytesPerWrite,FreeMegabytes from Win32_PerfFormattedData_PerfDisk_LogicalDisk"  # noqa

    connection.ExecQuery(wql, "WQL", query_flags)

    return True

if __name__ == '__main__':
    """
    Infinte loop: trigger 3 threads to connect and query WMI
    """
    threads = []
    last_gc = None

    while True:
        threading.Thread(target=connect_and_query)
        time.sleep(3)
        print "Objects=%s" % len(gc.get_objects())
        gc.collect()
        print "Objects=%s" % len(gc.get_objects())
