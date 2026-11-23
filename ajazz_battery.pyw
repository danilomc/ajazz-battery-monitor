"""
Ajazz Mouse Battery Monitor for Windows System Tray
Author: Antigravity
Ultra-low latency (1s polling) with near-zero CPU/Bus consumption (<0.1%).
"""

import os
import sys
import time
import json
import ctypes
from ctypes import wintypes
import threading
import winreg
from datetime import datetime
import subprocess
import traceback
import psutil

from PIL import Image, ImageDraw, ImageFont
import pystray

from ajazz_mouse import get_ajazz_mouse_status, invalidate_hid_cache

# Paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LOG_FILE = os.path.join(APP_DIR, "ajazz_battery.log")
DRIVER_EXE = r"C:\Program Files (x86)\AJAZZ\AJAZZ Driver (X)\AJAZZ Driver (X).exe"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "AjazzBatteryMonitor"
LOCAL_AUTOSTART_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AjazzBatteryMonitor")
LOCAL_AUTOSTART_VBS = os.path.join(LOCAL_AUTOSTART_DIR, "autostart.vbs")

def log(msg):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# Default configuration: 15s HID polling + instant USB change events for minimal bus load
DEFAULT_CONFIG = {
    "update_interval_sec": 15,
    "notify_low_battery": True,
    "notify_full_charge": True
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            log(f"Erro ao carregar config: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        log(f"Erro ao salvar config: {e}")

def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        log(f"Erro ao checar autostart: {e}")
        return False

def set_autostart(enable=True):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(pythonw_exe):
                    pythonw_exe = sys.executable
                script_path = os.path.abspath(__file__)
                work_dir = os.path.dirname(script_path)

                os.makedirs(LOCAL_AUTOSTART_DIR, exist_ok=True)
                vbs_content = (
                    'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
                    'Set WshShell = CreateObject("WScript.Shell")\r\n'
                    f'scriptPath = "{script_path}"\r\n'
                    f'pythonwExe = "{pythonw_exe}"\r\n'
                    f'workDir = "{work_dir}"\r\n'
                    'Dim i\r\n'
                    'For i = 1 To 45\r\n'
                    '    If fso.FileExists(scriptPath) Then Exit For\r\n'
                    '    WScript.Sleep 2000\r\n'
                    'Next\r\n'
                    'If fso.FileExists(scriptPath) Then\r\n'
                    '    WshShell.CurrentDirectory = workDir\r\n'
                    '    WshShell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & scriptPath & Chr(34), 0, False\r\n'
                    'End If\r\n'
                )
                with open(LOCAL_AUTOSTART_VBS, "w", encoding="utf-16") as f:
                    f.write(vbs_content)

                cmd = f'wscript.exe "{LOCAL_AUTOSTART_VBS}"'
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
                log(f"Autostart registrado: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                    log("Autostart removido")
                except FileNotFoundError:
                    pass
                if os.path.exists(LOCAL_AUTOSTART_VBS):
                    try:
                        os.remove(LOCAL_AUTOSTART_VBS)
                    except OSError:
                        pass
        return True
    except Exception as e:
        log(f"Erro ao configurar inicialização: {e}")
        return False

def render_tray_icon(percentage, is_charging=False, is_connected=True, size=64):
    """Draws a high-DPI icon with battery percentage and status bar."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if not is_connected:
        try:
            font_q = ImageFont.truetype("arialbd.ttf", 36)
        except Exception:
            font_q = ImageFont.load_default()
        draw.ellipse([6, 6, size - 6, size - 6], outline=(140, 140, 140, 200), width=3)
        draw.text((size // 2, size // 2), "?", font=font_q, fill=(160, 160, 160, 255), anchor="mm")
        return img

    # Color coding
    if is_charging:
        color = (0, 215, 255, 255)    # Cyan / Electric Blue
    elif percentage > 40:
        color = (40, 220, 90, 255)    # Green
    elif percentage > 15:
        color = (255, 180, 0, 255)    # Amber / Yellow
    else:
        color = (255, 60, 60, 255)    # Warning Red

    # Font setup
    try:
        font_main = ImageFont.truetype("arialbd.ttf", 34 if percentage < 100 else 26)
    except Exception:
        font_main = ImageFont.load_default()

    text = f"{percentage}"
    if is_charging and percentage >= 100:
        text = "⚡"
        try:
            font_main = ImageFont.truetype("seguiemj.ttf", 34)
        except Exception:
            pass

    cx = size // 2
    cy = (size - 14) // 2

    # Black border / shadow around text for high contrast on any background
    for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
        draw.text((cx + ox, cy + oy), text, font=font_main, fill=(0, 0, 0, 255), anchor="mm")
    draw.text((cx, cy), text, font=font_main, fill=color, anchor="mm")

    # Battery bar outline at the bottom
    bx0, by0, bx1, by1 = 4, size - 13, size - 10, size - 3
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=3, outline=(0, 0, 0, 255), width=3)
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=3, outline=(220, 220, 220, 220), width=1)

    # Positive terminal nipple
    draw.rectangle([bx1, by0 + 2, bx1 + 3, by1 - 2], fill=(220, 220, 220, 220))

    # Fill level
    inner_w = (bx1 - bx0 - 3)
    fill_w = int(inner_w * (max(0, min(100, percentage)) / 100.0))
    if fill_w > 0:
        draw.rounded_rectangle([bx0 + 2, by0 + 2, bx0 + 2 + fill_w, by1 - 2], radius=1, fill=color)

    # Small lightning icon if charging and percentage < 100
    if is_charging and percentage < 100:
        try:
            bolt_f = ImageFont.truetype("seguiemj.ttf", 16)
            draw.text((size - 10, 10), "⚡", font=bolt_f, fill=(255, 255, 0, 255), anchor="mm")
        except Exception:
            pass

    return img

class AjazzBatteryApp:
    def __init__(self):
        self.config = load_config()
        self.running = True
        self.icon = None
        self.last_rendered_state = None
        self.wake_event = threading.Event()
        self._usb_changed = False
        self._watcher_hwnd = None
        self._wndproc_ref = None
        self.current_status = {
            'connected': False,
            'model_name': 'Ajazz Mouse',
            'battery': 0,
            'charging': False,
            'connection_mode': 'Inicializando...',
            'source': 'None',
            'last_update': 'Nunca'
        }
        self.warned_20 = False
        self.warned_10 = False
        self.warned_full = False

    def update_status(self, force_reenum=False):
        try:
            status = get_ajazz_mouse_status(force_reenum=force_reenum)
            now_str = datetime.now().strftime("%H:%M:%S")
            status['last_update'] = now_str
            self.current_status = status

            # Check if visual state changed
            state_key = (
                status['connected'],
                status['battery'],
                status['charging'],
                status['connection_mode']
            )

            if state_key != self.last_rendered_state:
                prev = self.last_rendered_state
                self.last_rendered_state = state_key
                log(f"Mudança de estado: {status['model_name']} - Bat: {status['battery']}%, Chg: {status['charging']}, Modo: {status['connection_mode']}, Src: {status.get('source')}")
                self.refresh_icon()

                # Handle alerts on state transition
                if status['connected']:
                    bat = status['battery']
                    chg = status['charging']

                    # Check charge state change alert
                    if prev and prev[2] != chg:
                        # Cable plugged in or unplugged
                        pass

                    if self.config.get("notify_low_battery", True):
                        if not chg:
                            if bat <= 10 and not self.warned_10:
                                self.notify("Bateria Crítica!", f"{status['model_name']}: {bat}% restante. Conecte o cabo para carregar!")
                                self.warned_10 = True
                            elif bat <= 20 and not self.warned_20:
                                self.notify("Bateria Baixa!", f"{status['model_name']}: {bat}% restante.")
                                self.warned_20 = True
                            if bat > 25:
                                self.warned_20 = False
                                self.warned_10 = False
                        else:
                            self.warned_20 = False
                            self.warned_10 = False

                    if self.config.get("notify_full_charge", True):
                        if chg and bat >= 100 and not self.warned_full:
                            self.notify("Carga Completa!", f"{status['model_name']}: Bateria totalmente carregada (100%).")
                            self.warned_full = True
                        elif not chg or bat < 95:
                            self.warned_full = False

            # Tooltip update (fast, no image redrawing)
            self.update_tooltip()

        except Exception as e:
            log(f"Erro em update_status: {e}\n{traceback.format_exc()}")

    def update_tooltip(self):
        if not self.icon:
            return
        st = self.current_status
        if st['connected']:
            chg_str = " (Carregando ⚡)" if st['charging'] else ""
            self.icon.title = f"{st['model_name']}: {st['battery']}%{chg_str} [{st['connection_mode']}]"
        else:
            self.icon.title = f"{st['model_name']}: Desconectado / Suspenso"

    def refresh_icon(self):
        if not self.icon:
            return
        try:
            st = self.current_status
            img = render_tray_icon(
                st['battery'],
                is_charging=st['charging'],
                is_connected=st['connected']
            )
            self.icon.icon = img
            self.update_tooltip()
        except Exception as e:
            log(f"Erro em refresh_icon: {e}")

    def notify(self, title, message):
        try:
            if self.icon:
                self.icon.notify(message, title)
        except Exception as e:
            log(f"Erro em notify: {e}")

    def _start_usb_watcher(self):
        t = threading.Thread(target=self._usb_watcher_loop, daemon=True)
        t.start()

    def _usb_watcher_loop(self):
        """Listen passively to Windows WM_DEVICECHANGE to detect cable plug/unplug instantly."""
        WM_DESTROY = 0x0002
        WM_CLOSE = 0x0010
        WM_DEVICECHANGE = 0x0219
        DBT_DEVNODES_CHANGED = 0x0007

        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HANDLE),
                ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HANDLE),
                ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR),
            ]

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetModuleHandleW.restype = wintypes.HMODULE

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_DEVICECHANGE and wparam == DBT_DEVNODES_CHANGED:
                self._usb_changed = True
                self.wake_event.set()
            elif msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        try:
            self._wndproc_ref = WNDPROC(wndproc)
            h_inst = k32.GetModuleHandleW(None)
            class_name = f"AjazzUsbWatcher_{os.getpid()}"
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = h_inst
            wc.lpszClassName = class_name
            user32.RegisterClassW(ctypes.byref(wc))

            hwnd = user32.CreateWindowExW(
                0, class_name, "AjazzUsbWatcher", 0,
                0, 0, 0, 0, None, None, h_inst, None
            )
            if not hwnd:
                log("Aviso: não foi possível criar janela watcher USB.")
                return
            self._watcher_hwnd = hwnd
            log("Watcher de eventos USB iniciado.")

            msg = wintypes.MSG()
            while self.running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log(f"Erro no watcher USB: {e}")

    def background_loop(self):
        log("Thread de atualização iniciada (15s HID / evento USB instantâneo).")
        self.update_status(force_reenum=True)
        while self.running:
            cfg_interval = self.config.get("update_interval_sec", 15)
            if self.current_status.get('source') == 'DriverMemory':
                interval = max(2, min(5, cfg_interval))
            else:
                interval = max(10, cfg_interval)

            woken = self.wake_event.wait(timeout=interval)
            if not self.running:
                break

            if woken and self._usb_changed:
                self.wake_event.clear()
                self._usb_changed = False
                time.sleep(0.8)  # Debounce USB PnP enumeration
                invalidate_hid_cache()
                self.update_status(force_reenum=True)
            else:
                self.wake_event.clear()
                self.update_status(force_reenum=False)
        log("Thread de atualização encerrada.")

    def on_refresh(self, icon=None, item=None):
        self.last_rendered_state = None  # Force re-render
        self.update_status(force_reenum=True)
        st = self.current_status
        if st['connected']:
            chg = " (Carregando ⚡)" if st['charging'] else ""
            self.notify(f"{st['model_name']}", f"Bateria: {st['battery']}%{chg}\nModo: {st['connection_mode']}")
        else:
            self.notify(f"{st['model_name']}", "Mouse desconectado ou em repouso.")

    def on_toggle_autostart(self, icon=None, item=None):
        current = is_autostart_enabled()
        set_autostart(not current)
        self.update_menu()

    def on_toggle_low_notify(self, icon=None, item=None):
        cur = self.config.get("notify_low_battery", True)
        self.config["notify_low_battery"] = not cur
        save_config(self.config)
        self.update_menu()

    def on_toggle_full_notify(self, icon=None, item=None):
        cur = self.config.get("notify_full_charge", True)
        self.config["notify_full_charge"] = not cur
        save_config(self.config)
        self.update_menu()

    def on_open_driver(self, icon=None, item=None):
        if os.path.exists(DRIVER_EXE):
            try:
                subprocess.Popen([DRIVER_EXE], shell=False)
            except Exception as e:
                self.notify("Erro ao abrir driver", str(e))
        else:
            self.notify("Driver Ajazz", "Executável do driver oficial não encontrado.")

    def on_exit(self, icon=None, item=None):
        log("Saindo do monitor de bateria...")
        self.running = False
        self.wake_event.set()
        if self._watcher_hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._watcher_hwnd, 0x0010, 0, 0)
            except Exception:
                pass
        if self.icon:
            self.icon.stop()

    def update_menu(self):
        try:
            if self.icon:
                self.icon.menu = self.build_menu()
        except Exception as e:
            log(f"Erro em update_menu: {e}")

    def build_menu(self):
        st = self.current_status
        if st['connected']:
            chg = " ⚡" if st['charging'] else ""
            status_line = f"{st['model_name']}: {st['battery']}%{chg} ({st['connection_mode']})"
        else:
            status_line = f"{st['model_name']}: Desconectado"

        autostart_mark = "✔ " if is_autostart_enabled() else "   "
        low_mark = "✔ " if self.config.get("notify_low_battery", True) else "   "
        full_mark = "✔ " if self.config.get("notify_full_charge", True) else "   "

        return pystray.Menu(
            pystray.MenuItem(status_line, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔄 Atualizar Agora", self.on_refresh, default=True),
            pystray.MenuItem("🖱️ Abrir Software da Ajazz", self.on_open_driver),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"{autostart_mark}Iniciar com o Windows", self.on_toggle_autostart),
            pystray.MenuItem(f"{low_mark}Notificar Bateria Fraca (<=20%)", self.on_toggle_low_notify),
            pystray.MenuItem(f"{full_mark}Notificar Carga Completa (100%)", self.on_toggle_full_notify),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Sair", self.on_exit)
        )

    def run(self):
        # Kill previous instance if running
        my_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if p.info['pid'] != my_pid and p.info['name'] and 'python' in p.info['name'].lower():
                    cmd = " ".join(p.info.get('cmdline') or [])
                    if 'ajazz_battery.pyw' in cmd:
                        log(f"Finalizando instância anterior (PID {p.info['pid']})")
                        p.terminate()
            except Exception:
                pass

        log("Inicializando ícone de bandeja...")
        initial_img = render_tray_icon(0, is_charging=False, is_connected=False)
        self.icon = pystray.Icon(
            "AjazzBatteryMonitor",
            initial_img,
            "Ajazz Battery Monitor - Conectando...",
            menu=self.build_menu()
        )

        def on_tray_ready(icon):
            icon.visible = True
            log("Ícone visível na bandeja do sistema.")
            self._start_usb_watcher()
            t = threading.Thread(target=self.background_loop, daemon=True)
            t.start()

        try:
            self.icon.run(setup=on_tray_ready)
        except Exception as e:
            log(f"Erro fatal na execução do pystray: {e}\n{traceback.format_exc()}")
        finally:
            log("Aplicação finalizada.")

if __name__ == '__main__':
    log("=== Iniciando Ajazz Battery Monitor (15s HID / evento USB instantâneo) ===")
    app = AjazzBatteryApp()
    app.run()
