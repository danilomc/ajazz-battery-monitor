"""
Ajazz Mouse Battery Reader Module
Robust non-blocking HID communication with timeout, path caching, and driver process memory fallback.
"""

import ctypes
from ctypes import wintypes
import struct
import psutil

# Windows API Constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
WAIT_OBJECT_0 = 0
ERROR_IO_PENDING = 997

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

setupapi = ctypes.windll.setupapi
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

hid = ctypes.windll.hid
kernel32 = ctypes.windll.kernel32

class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', wintypes.BYTE * 8)
    ]

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('InterfaceClassGuid', GUID),
        ('Flags', wintypes.DWORD),
        ('Reserved', ctypes.c_size_t)
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('th32ModuleID', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('GlblcntUsage', wintypes.DWORD),
        ('ProccntUsage', wintypes.DWORD),
        ('modBaseAddr', ctypes.c_void_p),
        ('modBaseSize', wintypes.DWORD),
        ('hModule', wintypes.HMODULE),
        ('szModule', ctypes.c_char * 256),
        ('szExePath', ctypes.c_char * 260)
    ]

class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ('Internal', ctypes.c_size_t),
        ('InternalHigh', ctypes.c_size_t),
        ('Offset', wintypes.DWORD),
        ('OffsetHigh', wintypes.DWORD),
        ('hEvent', wintypes.HANDLE)
    ]

MODEL_MAP = {
    'M179': 'Ajazz AJ179',
    'M179A': 'Ajazz AJ179',
    'M603': 'Ajazz AJ179',
    'M129': 'Ajazz AJ139 Pro',
    'M139': 'Ajazz AJ139 Pro / V2',
    'M620': 'Ajazz AJ159',
    'M630': 'Ajazz AJ159 MC',
    'N620': 'Ajazz AJ159P MC',
    'N624': 'Ajazz AJ179 V2',
    'N625': 'Ajazz AJ179 V2 MAX',
    'M184': 'Ajazz AJ179',
}

_cached_active_path = None

def format_model_name(code):
    clean = code.strip().upper()
    for key, name in MODEL_MAP.items():
        if key in clean or clean in key:
            return name
    return f"Ajazz ({clean})" if clean else "Ajazz Mouse"

def find_ajazz_hid_paths():
    """Enumerate all HID device paths matching Ajazz VIDs and MI_02 interface."""
    hid_guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(hid_guid))
    hDevInfo = setupapi.SetupDiGetClassDevsW(ctypes.byref(hid_guid), None, None, 0x12)
    if hDevInfo == -1 or not hDevInfo:
        return []

    paths = []
    idx = 0
    try:
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(hDevInfo, None, ctypes.byref(hid_guid), idx, ctypes.byref(did)):
                break
            idx += 1

            req_size = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(hDevInfo, ctypes.byref(did), None, 0, ctypes.byref(req_size), None)
            if req_size.value > 0:
                buf = ctypes.create_string_buffer(req_size.value)
                struct_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
                ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(struct_size)), 4)
                if setupapi.SetupDiGetDeviceInterfaceDetailW(hDevInfo, ctypes.byref(did), buf, req_size.value, None, None):
                    path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                    plow = path.lower()
                    if ('vid_248a' in plow or 'vid_249a' in plow) and 'mi_02' in plow:
                        paths.append(path)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
    return paths

def query_mouse_hid(path, timeout_ms=40):
    """Query mouse using non-blocking Overlapped I/O with timeout."""
    hDev = kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED,
        None
    )
    if hDev == -1 or not hDev:
        return None

    hWriteEvent = kernel32.CreateEventW(None, True, False, None)
    hReadEvent = kernel32.CreateEventW(None, True, False, None)

    try:
        # 33-byte query packet: byte 0 = 0x00, byte 1 = 0x10
        packet = bytearray(33)
        packet[0] = 0x00
        packet[1] = 0x10

        ov_write = OVERLAPPED()
        ov_write.hEvent = hWriteEvent
        written = wintypes.DWORD()

        res = kernel32.WriteFile(hDev, (ctypes.c_char * 33).from_buffer(packet), 33, ctypes.byref(written), ctypes.byref(ov_write))
        if not res:
            err = kernel32.GetLastError()
            if err == ERROR_IO_PENDING:
                if kernel32.WaitForSingleObject(hWriteEvent, timeout_ms) == WAIT_OBJECT_0:
                    kernel32.GetOverlappedResult(hDev, ctypes.byref(ov_write), ctypes.byref(written), False)
                else:
                    kernel32.CancelIo(hDev)
                    return None
            else:
                return None

        # Overlapped Read
        read_buf = bytearray(33)
        ov_read = OVERLAPPED()
        ov_read.hEvent = hReadEvent
        bytes_read = wintypes.DWORD()

        res_read = kernel32.ReadFile(hDev, (ctypes.c_char * 33).from_buffer(read_buf), 33, ctypes.byref(bytes_read), ctypes.byref(ov_read))
        got_data = False
        if not res_read:
            err = kernel32.GetLastError()
            if err == ERROR_IO_PENDING:
                if kernel32.WaitForSingleObject(hReadEvent, timeout_ms) == WAIT_OBJECT_0:
                    kernel32.GetOverlappedResult(hDev, ctypes.byref(ov_read), ctypes.byref(bytes_read), False)
                    got_data = True
                else:
                    kernel32.CancelIo(hDev)
                    return None
            else:
                return None
        else:
            got_data = True

        if not got_data or bytes_read.value != 33:
            return None

        model_code = read_buf[5:10].decode('ascii', errors='ignore').rstrip('\x00')
        charging = bool(read_buf[13])
        battery = int(read_buf[14])

        if battery > 100:
            battery = 100

        is_wireless = ('pid_5c2f' in path.lower() or 'vid_249a' in path.lower())

        return {
            'connected': True,
            'model_code': model_code,
            'model_name': format_model_name(model_code),
            'battery': battery,
            'charging': charging,
            'connection_mode': '2.4G Sem Fio' if is_wireless else 'Cabo USB',
            'source': 'HID'
        }
    except Exception:
        return None
    finally:
        if hWriteEvent:
            kernel32.CloseHandle(hWriteEvent)
        if hReadEvent:
            kernel32.CloseHandle(hReadEvent)
        kernel32.CloseHandle(hDev)

_cached_driver_pid = None
_cached_driver_base_addr = None
_cached_driver_proc = None

def get_ajazz_driver_info():
    """
    Returns (pid, base_addr) if Ajazz Driver is running, else (None, None).
    Caches the process object and base address for near-instant checks.
    """
    global _cached_driver_pid, _cached_driver_base_addr, _cached_driver_proc

    if _cached_driver_proc is not None:
        try:
            if _cached_driver_proc.is_running() and _cached_driver_proc.status() != psutil.STATUS_ZOMBIE:
                return _cached_driver_pid, _cached_driver_base_addr
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        _cached_driver_pid = None
        _cached_driver_base_addr = None
        _cached_driver_proc = None

    # Search for running Ajazz Driver process
    try:
        for p in psutil.process_iter(['pid', 'name']):
            name = p.info.get('name') or ''
            if 'ajazz' in name.lower() and name.lower().endswith('.exe'):
                pid = p.info['pid']
                hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
                if hSnapshot and hSnapshot != -1:
                    try:
                        me = MODULEENTRY32()
                        me.dwSize = ctypes.sizeof(MODULEENTRY32)
                        success = kernel32.Module32First(hSnapshot, ctypes.byref(me))
                        while success:
                            mod_name = me.szModule.decode('latin1', errors='replace').lower()
                            if 'ajazz' in mod_name and mod_name.endswith('.exe'):
                                _cached_driver_pid = pid
                                _cached_driver_base_addr = me.modBaseAddr
                                _cached_driver_proc = p
                                return pid, me.modBaseAddr
                            success = kernel32.Module32Next(hSnapshot, ctypes.byref(me))
                    finally:
                        kernel32.CloseHandle(hSnapshot)
    except Exception:
        pass

    return None, None

def query_mouse_driver_memory():
    """Query battery info from official Ajazz Driver process memory if running."""
    pid, base_addr = get_ajazz_driver_info()
    if not pid or not base_addr:
        return None

    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        return None

    try:
        def read_mem(addr, size):
            buf = ctypes.create_string_buffer(size)
            bytesRead = ctypes.c_size_t()
            if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(bytesRead)):
                return buf.raw
            return None

        target_addr = base_addr + 0x18963C
        mgr_data = read_mem(target_addr, 0x40)
        if not mgr_data:
            return None

        dev_start, dev_end = struct.unpack_from('<II', mgr_data, 8)
        num_devices = (dev_end - dev_start) // 4
        if num_devices <= 0:
            return None

        for idx in range(num_devices):
            ptr_data = read_mem(dev_start + idx * 4, 4)
            if not ptr_data:
                continue
            dev_ptr = struct.unpack_from('<I', ptr_data, 0)[0]
            dev_data = read_mem(dev_ptr, 0x500)
            if not dev_data:
                continue

            mode = struct.unpack_from('<I', dev_data, 0x420)[0]
            connected = struct.unpack_from('<I', dev_data, 0x424)[0]
            report = dev_data[0x42C : 0x42C + 65]

            model_code = report[4:9].decode('ascii', errors='replace').rstrip('\x00')
            charging = bool(report[12])
            battery = int(report[13])

            if battery > 100:
                battery = 100

            return {
                'connected': bool(connected),
                'model_code': model_code,
                'model_name': format_model_name(model_code),
                'battery': battery,
                'charging': charging,
                'connection_mode': '2.4G Sem Fio' if mode == 1 else 'Cabo USB',
                'source': 'DriverMemory'
            }
    except Exception:
        return None
    finally:
        kernel32.CloseHandle(handle)
    return None

def get_ajazz_mouse_status():
    """
    Primary API function to get current mouse battery status.
    - If official Ajazz Driver is running: 100% passive memory reading.
      NEVER sends any HID packets over USB/HID, eliminating 100% of driver popups.
    - If official Ajazz Driver is NOT running: uses direct Windows HID Overlapped I/O.
    """
    global _cached_active_path

    # Check if official Ajazz Driver is running
    pid, _ = get_ajazz_driver_info()
    if pid:
        # Official driver is running! We MUST NOT touch HID under any circumstances.
        mem_info = query_mouse_driver_memory()
        if mem_info:
            return mem_info
        return {
            'connected': False,
            'model_code': '',
            'model_name': 'Ajazz Mouse',
            'battery': 0,
            'charging': False,
            'connection_mode': 'Driver em Inicialização',
            'source': 'DriverMemory'
        }

    # If we reached here, the official driver is NOT running at all.
    # Direct HID querying is 100% safe since there is no driver open to show popups.

    # 1. Fast Path: Cached active HID path
    if _cached_active_path:
        info = query_mouse_hid(_cached_active_path, timeout_ms=30)
        if info and info['battery'] > 0:
            return info
        _cached_active_path = None

    # 2. Direct HID query via path enumeration
    paths = find_ajazz_hid_paths()
    for p in paths:
        info = query_mouse_hid(p, timeout_ms=50)
        if info and info['battery'] > 0:
            _cached_active_path = p
            return info

    return {
        'connected': False,
        'model_code': '',
        'model_name': 'Ajazz Mouse',
        'battery': 0,
        'charging': False,
        'connection_mode': 'Desconectado',
        'source': 'None'
    }

if __name__ == '__main__':
    status = get_ajazz_mouse_status()
    print("Mouse Status:")
    for k, v in status.items():
        print(f"  {k}: {v}")
