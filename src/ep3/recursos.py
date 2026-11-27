"""Recursos del proceso con biblioteca estándar; nunca estima RAM desconocida."""
import os
from functools import lru_cache
from time import process_time

@lru_cache(maxsize=1)
def _api_windows():
    """Cachear solo clases/funciones nativas; cada muestra conserva su estructura propia."""
    import ctypes
    from ctypes import wintypes
    class Contadores(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    *[(n, ctypes.c_size_t) for n in ('PeakWorkingSetSize', 'WorkingSetSize',
                      'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                      'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
    return Contadores,api,kernel.GetCurrentProcess()

def muestra() -> tuple[float, int | None, str]:
    cpu = process_time()
    if os.name == 'nt':
        import ctypes
        clase,api,handle = _api_windows()
        datos=clase();datos.cb=ctypes.sizeof(datos)
        if api(handle, ctypes.byref(datos), datos.cb):
            return cpu, int(datos.WorkingSetSize), 'working_set'
    elif os.path.exists('/proc/self/statm'):
        with open('/proc/self/statm', encoding='ascii') as f:
            return cpu, int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE'), 'rss_proc'
    return cpu, None, 'no_disponible'
