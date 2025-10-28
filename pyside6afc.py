# in beta- install pyside6 before usage
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from pymobiledevice3.lockdown import create_using_usbmux
try:
    from pymobiledevice3.lockdown import MissingValue
except ImportError:
    MissingValue = None
from pymobiledevice3.exceptions import PyMobileDevice3Exception
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3.services.installation_proxy import InstallationProxyService
from pymobiledevice3.services.house_arrest import HouseArrestService
from pymobiledevice3.services.diagnostics import DiagnosticsService
from pymobiledevice3.services.screenshot import ScreenshotService
from pymobiledevice3.services.syslog import SyslogService
from pymobiledevice3.services.mounter import MounterService
from pymobiledevice3.usbmux import list_devices
import threading
import json
import os
import sys
import time
import base64
import stat
from PIL import Image, ImageTk

from PySide6.QtCore import (
    QObject, QThread, Signal, Qt, QSize, QEvent
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QDialog, QTextEdit, QTabWidget, QMenuBar,
    QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QGridLayout, QScrollArea, QFrame, QSizePolicy, QMessageBox,
    QFileDialog, QMenu
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QAction, QPixmap, QIcon, QCursor
)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

STYLESHEET = """
    QMainWindow, QDialog, QWidget {
        background-color: #242424;
        color: #DCE4EE;
        font-family: "Segoe UI";
    }
    QTabWidget::pane {
        border: 1px solid #323232;
        border-top: 1px solid #3A3A3A;
    }
    QTabBar::tab {
        background: #2B2B2B;
        color: #AAB0B6;
        padding: 10px 20px;
        font-size: 13px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }
    QTabBar::tab:selected {
        background: #1F6AA5;
        color: white;
    }
    QTextEdit, QListWidget, QLineEdit {
        background-color: #2B2B2B;
        color: #DCE4EE;
        border: 1px solid #3A3A3A;
        border-radius: 5px;
        padding: 5px;
        font-size: 11px;
    }
    QListWidget::item:hover {
        background-color: #3A3A3A;
    }
    QListWidget::item:selected {
        background-color: #36719F;
        color: white;
    }
    QPushButton {
        background-color: #1F6AA5;
        color: white;
        border-radius: 5px;
        padding: 10px;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #1A5A90;
    }
    QPushButton#InstallBtn {
        background-color: #006400;
    }
    QPushButton#InstallBtn:hover {
        background-color: #004D00;
    }
    QPushButton#HelpBtn {
        font-size: 12px;
        font-weight: normal;
        text-decoration: underline;
        color: #87CEFA;
        background-color: transparent;
        border: none;
    }
    QScrollArea {
        border: none;
        background-color: transparent;
    }
    #AppFrame {
        background-color: #2B2B2B;
        border: 1px solid #3A3A3A;
        border-radius: 5px;
    }
    #AppFrame:hover {
        background-color: #3A3A3A;
    }
    QMenu {
        background-color: #2B2B2B;
        color: white;
        border: 1px solid #3A3A3A;
        font-size: 13px;
    }
    QMenu::item:selected {
        background-color: #36719F;
    }
    QMenu::separator {
        height: 1px;
        background: #3A3A3A;
        margin: 5px 0;
    }
    QMenuBar {
        background-color: #2B2B2B;
        color: white;
        font-size: 13px;
    }
    QMenuBar::item:selected {
        background-color: #36719F;
    }
"""

LARGE_FONT = QFont("Segoe UI", 24, QFont.Weight.Bold)
MAIN_FONT = QFont("Segoe UI", 13)
MONO_FONT = QFont("Consolas", 12)
LIST_FONT = QFont("Segoe UI", 11)
LOG_FONT = QFont("Consolas", 10)
APP_GRID_FONT = QFont("Segoe UI", 10)
LINK_FONT = QFont("Segoe UI", 12, QFont.Weight.Normal)

def json_bytes_handler(obj):
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return repr(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

class DeviceLogic(QObject):
    log_message = Signal(str)
    connection_failed = Signal(str)
    connection_successful = Signal(str, dict, list, tuple)

    device_info_updated = Signal(str)
    file_list_updated = Signal(list, list, object)
    app_list_updated = Signal(list, object)
    
    action_finished = Signal(str, str)
    action_error = Signal(str, str)
    
    syslog_message = Signal(str)
    syslog_stopped = Signal()
    device_disconnected = Signal(str)

    def __init__(self):
        super().__init__()
        self.client = None
        self.afc = None
        self.current_path = "/"
        self.is_jailbroken = False
        self.stop_listener = threading.Event()
        self.stop_syslog_event = threading.Event()
        self.syslog_thread = None

    def start_device_listener(self):
        self.stop_listener.clear()
        print("LISTENER: Started device listener thread.")
        while not self.stop_listener.is_set():
            try:
                devices = list_devices()
                if devices:
                    udid = devices[0].serial
                    print(f"LISTENER: Found device: {udid}")
                    self.connect_to_device(udid)
                    break
                else:
                    self.log_message.emit("Waiting for device...")
            except Exception as e:
                print(f"LISTENER: Error: {e}")
                self.connection_failed.emit(f"Listener Error: {e}")
                break
            time.sleep(2)
        print("LISTENER: Stopped device listener thread.")

    def stop_all_activity(self):
        print("LOGIC: Stop signal received")
        self.stop_listener.set()
        self.stop_syslog_event.set()
        if self.client:
            try:
                self.client.close()
                print("LOGIC: Lockdown client closed.")
            except Exception as e:
                print(f"LOGIC: Error closing client: {e}")
        self.client = None
        self.afc = None

    def connect_to_device(self, udid):
        print(f"LOGIC: connect_device function started for {udid}")
        client_instance = None
        device_name = "Unknown Device"
        all_values = None
        preloaded_apps = []
        preloaded_files_data = ([], [], None)

        try:
            self.log_message.emit(f"Connecting to {udid} via USB...")
            client_instance = create_using_usbmux(serial=udid)
            self.log_message.emit("Connection successful. Stabilizing...")
            time.sleep(1)

            self.log_message.emit("Fetching device info...")
            try:
                all_values = client_instance.get_value(None)
                if not all_values or not isinstance(all_values, dict):
                    raise PyMobileDevice3Exception(f"Invalid data: {all_values!r}")
                device_name = all_values.get("DeviceName", None)
                if not device_name or not isinstance(device_name, str):
                     raise PyMobileDevice3Exception(f"Invalid DeviceName: {device_name!r}")
                self.log_message.emit(f"Got device info. Name: {device_name}")
                self.client = client_instance
            except (PyMobileDevice3Exception, MissingValue if MissingValue else PyMobileDevice3Exception) as get_value_error:
                self.log_message.emit(f"ERROR: Failed get values: {get_value_error}")
                self.connection_failed.emit(f"Connected but failed info.\nPairing issue?\n\nError: {get_value_error}")
                if client_instance:
                    try: client_instance.close()
                    except Exception as ce: print(f"LOGIC: Close error 1: {ce}")
                return

            self.log_message.emit("Attempting to mount Developer Image...")
            try:
                with MounterService(self.client) as mounter:
                    mounter.mount_developer_image()
                self.log_message.emit("Developer Image mounted successfully.")
            except Exception as mount_error:
                self.log_message.emit(f"WARNING: Failed to mount Developer Image: {mount_error}")
                self.log_message.emit("Device actions (Screenshot, Reboot) may fail.")

            self.log_message.emit("Starting AFC service...")
            self.start_afc_service()
            if not self.afc:
                 self.connection_failed.emit("Failed AFC service start.")
                 return

            self.log_message.emit(f"Fetching initial file list for {self.current_path}...")
            preloaded_files_data = self._get_file_list_sync(self.current_path)
            f, fl, e = preloaded_files_data
            if e: self.log_message.emit(f"Warning: Error fetching files: {e}")
            else: self.log_message.emit(f"Fetched initial files: {len(f)} folders, {len(fl)} files.")

            self.log_message.emit("Fetching application list...")
            preloaded_apps, app_error = self._get_app_list_sync()
            self.apps_cache = preloaded_apps # Cache
            if app_error: self.log_message.emit(f"Warning: Error fetching apps: {app_error}")
            else: self.log_message.emit(f"Fetched {len(preloaded_apps)} applications.")

            self.log_message.emit("Pre-loading complete. Connection setup successful!")
            self.connection_successful.emit(device_name, all_values, preloaded_apps, preloaded_files_data)

        except Exception as e:
            print(f"LOGIC: Connect process failed: {e}")
            self.log_message.emit(f"ERROR: {e}")
            self.connection_failed.emit(f"Could not connect.\nTrusted?\niTunes/AMDS running?\n\nError: {e}")
            if client_instance and not self.client:
                try: client_instance.close()
                except Exception as ce: print(f"LOGIC: Close error 2: {ce}")

    def get_formatted_device_info(self, all_info=None):
        if not self.client and not all_info: return "Error: Not connected."
        try:
            if all_info is None:
                if not self.client: raise PyMobileDevice3Exception("Client unavailable")
                all_info = self.client.get_value(None)
                if not all_info: raise PyMobileDevice3Exception("Empty info")
            info = []
            keys = [
                ("DeviceName","Name"), ("ProductType","Model"),("HardwareModel","HW Model"),
                ("ProductName","OS"), ("ProductVersion","Version"), ("BuildVersion","Build"),
                ("UniqueDeviceID","UDID"), ("SerialNumber","Serial"), ("CPUArchitecture","CPU"),
                ("WiFiAddress","WiFi"), ("BluetoothAddress","BT"), ("TimeZone","Zone"),
                ("ActivationState","Act State")
            ]
            for k, l in keys:
                v = all_info.get(k, "N/A"); fv = repr(v)
                try: fv = json.dumps(v, default=json_bytes_handler).strip('"')
                except TypeError: pass
                info.append(f"{l}: {fv}")
            return "\n".join(info)
        except Exception as e:
            print(f"LOGIC: get_info FAILED: {e}")
            return f"Error fetching info:\n{e}"
    
    def refresh_device_info(self):
        if not self.client: return
        try:
            all_info = self.client.get_value(None)
            formatted_info = self.get_formatted_device_info(all_info)
            self.device_info_updated.emit(formatted_info)
        except Exception as e:
            self.action_error.emit("Info Error", f"Failed to refresh info: {e}")

    def start_afc_service(self):
        if not self.client: self.afc = None; return
        try:
            self.afc = AfcService(self.client); time.sleep(0.2)
            try:
                self.afc.listdir("/private")
                self.is_jailbroken = True; self.current_path = "/"
            except PyMobileDevice3Exception:
                self.is_jailbroken = False; self.current_path = "/"
        except Exception as e: self.afc = None; print(f"ERROR: AFC start fail: {e}")

    def _get_file_list_sync(self, path_to_list):
        folders, files, error_msg = [], [], None
        if not self.afc: return folders, files, "AFC service not ready"
        try:
            items = self.afc.listdir(path_to_list)
            for item in items:
                if item in ('.', '..'): continue
                fp = os.path.join(path_to_list, item).replace("\\", "/")
                is_dir = False
                try:
                    info = self.afc.stat(fp)
                    if hasattr(info, 'st_ifmt') and stat.S_ISDIR(info.st_ifmt): is_dir = True
                except (PyMobileDevice3Exception, AttributeError):
                    try: self.afc.listdir(fp); is_dir = True
                    except PyMobileDevice3Exception: is_dir = False
                if is_dir: folders.append(f"[FOLDER] {item}")
                else: files.append(item)
        except Exception as e: error_msg = e
        return folders, files, error_msg

    def fetch_file_list(self, path):
        if not self.afc: self.file_list_updated.emit([], [], "AFC not ready"); return
        self.current_path = path
        folders, files, error = self._get_file_list_sync(path)
        self.file_list_updated.emit(folders, files, error)

    def _get_app_list_sync(self):
        apps_data, error_msg = [], None
        if not self.client: return apps_data, "Client not connected"
        try:
            with InstallationProxyService(self.client) as ip:
                apps = ip.get_apps()
            if apps:
                for bundle_id, info in apps.items():
                    name = info.get('CFBundleDisplayName', bundle_id)
                    version = info.get('CFBundleShortVersionString', 'N/A')
                    app_type = info.get('ApplicationType', 'User')
                    apps_data.append((name, version, app_type, bundle_id))
        except Exception as e: error_msg = e
        return apps_data, error_msg

    def fetch_app_list(self):
        apps_data, error = self._get_app_list_sync()
        self.apps_cache = apps_data # Update cache
        self.app_list_updated.emit(apps_data, error)

    def upload_files(self, file_paths, dest_path):
        if not self.afc: self.action_error.emit("Upload Error", "AFC not connected."); return
        try:
            for p in file_paths:
                fn = os.path.basename(p); dp = os.path.join(dest_path, fn).replace("\\", "/")
                self.log_message.emit(f"Uploading {fn}...")
                self.afc.push(p, dp)
            self.action_finished.emit("Done", f"Uploaded {len(file_paths)} file(s).")
            self.fetch_file_list(dest_path)
        except Exception as e: self.action_error.emit("Upload Error", f"Upload failed: {e}")

    def download_files(self, file_names, save_dir):
        if not self.afc: self.action_error.emit("Download Error", "AFC not connected."); return
        try:
            for fn in file_names:
                sp = os.path.join(self.current_path, fn).replace("\\", "/"); pp = os.path.join(save_dir, fn)
                self.log_message.emit(f"Downloading {fn}...")
                self.afc.pull(sp, pp)
            self.action_finished.emit("Done", f"Downloaded {len(file_names)} file(s).")
        except Exception as e: self.action_error.emit("Download Error", f"Download failed: {e}")
    
    def install_app(self, ipa_path):
        if not self.client: self.action_error.emit("Install Error", "Not connected."); return
        try:
            self.log_message.emit(f"Installing {os.path.basename(ipa_path)}...")
            with InstallationProxyService(self.client) as ip: ip.install(ipa_path)
            self.action_finished.emit("Done", "Install successful.")
            self.fetch_app_list()
        except Exception as e: self.action_error.emit("Install Error", f"Install failed: {e}")

    def uninstall_app(self, bundle_id, app_name):
        if not self.client: self.action_error.emit("Uninstall Error", "Not connected."); return
        try:
            self.log_message.emit(f"Uninstalling {app_name}...")
            with InstallationProxyService(self.client) as ip: ip.uninstall(bundle_id)
            self.action_finished.emit("Done", f"'{app_name}' uninstalled.")
            self.fetch_app_list()
        except Exception as e: self.action_error.emit("Uninstall Error", f"Failed to uninstall {app_name}: {e}")

    def explore_app_documents(self, bundle_id):
        if not self.client: self.action_error.emit("Explore Error", "Not connected."); return
        contents, error = [], None
        try:
            with HouseArrestService(self.client, bundle_id=bundle_id, connection_type='DOCUMENTS') as ha:
                items = ha.listdir('/Documents')
                contents = sorted(items)
        except Exception as e: error = f"Could not explore:\n{e}"
        if error: self.action_error.emit("Explore Error", error)
        elif not contents: self.action_finished.emit("Explore Docs", f"App: {bundle_id}\n\nDocuments folder empty/inaccessible.")
        else: display = f"App: {bundle_id}\n\nDocuments:\n- " + "\n- ".join(contents); self.action_finished.emit("Explore Docs", display)

    def take_screenshot(self, save_path):
        if not self.client: self.action_error.emit("Screenshot Error", "Not connected."); return
        try:
            self.log_message.emit("Taking screenshot...")
            with ScreenshotService(self.client) as s: s.save(save_path)
            self.action_finished.emit("Success", f"Screenshot saved to:\n{save_path}")
        except Exception as e: self.action_error.emit("Screenshot Error", f"Failed to take screenshot:\n{e}")

    def get_battery_info(self):
        if not self.client: self.action_error.emit("Battery Error", "Not connected."); return
        try:
            with DiagnosticsService(self.client) as diag: info = diag.get_battery()
            level = info.get("BatteryCurrentCapacity", "N/A"); status = info.get("BatteryChargeStatus", "N/A")
            self.action_finished.emit("Battery Info", f"Battery Level: {level}%\nStatus: {status}")
        except Exception as e: self.action_error.emit("Battery Error", f"Failed to get battery info:\n{e}")

    def reboot_device(self):
        if not self.client: self.action_error.emit("Reboot Error", "Not connected."); return
        try:
            self.log_message.emit("Sending reboot command...")
            with DiagnosticsService(self.client) as diag: diag.restart()
            self.action_finished.emit("Reboot", "Device is rebooting. Connection will be lost.")
            self.device_disconnected.emit("Reboot initiated.")
        except Exception as e: self.action_error.emit("Reboot Error", f"Failed to reboot:\n{e}")

    def shutdown_device(self):
        if not self.client: self.action_error.emit("Shutdown Error", "Not connected."); return
        try:
            self.log_message.emit("Sending shutdown command...")
            with DiagnosticsService(self.client) as diag: diag.shutdown()
            self.action_finished.emit("Shutdown", "Device is powering off. Connection will be lost.")
            self.device_disconnected.emit("Shutdown initiated.")
        except Exception as e: self.action_error.emit("Shutdown Error", f"Failed to shutdown:\n{e}")

    def enter_recovery(self):
        if not self.client: self.action_error.emit("Recovery Error", "Not connected."); return
        try:
            self.log_message.emit("Sending recovery command...")
            with DiagnosticsService(self.client) as diag: diag.enter_recovery()
            self.action_finished.emit("Recovery", "Device entering recovery mode. Connection will be lost.")
            self.device_disconnected.emit("Recovery initiated.")
        except Exception as e: self.action_error.emit("Recovery Error", f"Failed to enter recovery:\n{e}")
    
    def start_syslog(self):
        if self.syslog_thread and self.syslog_thread.is_alive(): return
        if not self.client: self.action_error.emit("Syslog Error", "Not connected."); return
        self.stop_syslog_event.clear()
        def _stream_task():
            try:
                print("LOGIC: Starting syslog stream thread...")
                with SyslogService(self.client) as syslog:
                    for line in syslog.watch():
                        if self.stop_syslog_event.is_set(): break
                        self.syslog_message.emit(line)
            except Exception as e: print(f"LOGIC: Syslog stream error: {e}"); self.syslog_message.emit(f"\n--- SYSLOG ERROR: {e} ---\n")
            finally: print("LOGIC: Syslog stream thread finished."); self.syslog_stopped.emit()
        self.syslog_thread = threading.Thread(target=_stream_task, daemon=True)
        self.syslog_thread.start()

    def stop_syslog(self):
        print("LOGIC: Stopping syslog stream...")
        self.stop_syslog_event.set()


class PyAFCGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "PyAFC v2.0 (PySide6)"
        self.setWindowTitle(self.title)
        self.logic = None
        self.worker_thread = None
        self.log_dialog = None
        
        self.setup_menubar()
        self.setup_waiting_ui()
        self.center_window(400, 200)
        self.start_device_listener()

    def center_window(self, width, height):
        try:
            screen = self.screen().geometry()
            x = (screen.width() - width) // 2
            y = (screen.height() - height) // 2
            self.setGeometry(x, y, width, height)
        except Exception as e:
             print(f"Error centering window: {e}")
             self.resize(width, height)

    def center_toplevel(self, top_level, w, h):
         try:
            self.update_idletasks()
            main_geo = self.geometry()
            x = main_geo.x() + (main_geo.width() - w) // 2
            y = main_geo.y() + (main_geo.height() - h) // 2
            top_level.setGeometry(x, y, w, h)
         except Exception as e:
             print(f"Error centering toplevel: {e}")
             top_level.resize(w,h)

    def setup_waiting_ui(self):
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_widget.setLayout(layout)

        self.wait_label_main = QLabel("Please connect your device.")
        self.wait_label_main.setFont(LARGE_FONT)
        self.wait_label_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.wait_label_main)

        self.wait_label_status = QLabel("Waiting for devices...")
        self.wait_label_status.setFont(MAIN_FONT)
        self.wait_label_status.setStyleSheet("color: gray;")
        self.wait_label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.wait_label_status)
        
        self.help_button = QPushButton("Device not connecting?")
        self.help_button.setFont(LINK_FONT)
        self.help_button.setObjectName("HelpBtn")
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_button.clicked.connect(self.show_connection_help)
        layout.addWidget(self.help_button)
        layout.addStretch()

    def show_connection_help(self):
        help_text = (
            "- Ensure your iPhone has the computer trusted.\n\n"
            "- Ensure iTunes or Apple Devices (Microsoft Store) is installed.\n\n"
            "- Try a different device and see if it works properly.\n\n"
            "- Try a different cable and see if it works properly.\n\n"
            "- If none of these steps work, create an issue in our GitHub repo:\n"
            "  https://github.com/ZodaciOS/PyAFC/issues"
        )
        QMessageBox.information(self, "Connection Help", help_text)

    def start_device_listener(self):
        if self.worker_thread:
            self.logic.stop_all_activity()
            self.worker_thread.quit()
            self.worker_thread.wait()

        self.worker_thread = QThread()
        self.logic = DeviceLogic()
        self.logic.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(self.logic.start_device_listener)
        self.logic.log_message.connect(self.on_log_message)
        self.logic.connection_failed.connect(self.on_connection_failed)
        self.logic.connection_successful.connect(self.on_connection_successful)
        
        self.logic.device_info_updated.connect(self.on_device_info_updated)
        self.logic.file_list_updated.connect(self.on_file_list_updated)
        self.logic.app_list_updated.connect(self.on_app_list_updated)
        
        self.logic.action_finished.connect(self.on_action_finished)
        self.logic.action_error.connect(self.on_action_error)
        
        self.logic.syslog_message.connect(self.on_syslog_message)
        self.logic.syslog_stopped.connect(self.on_syslog_stopped)
        self.logic.device_disconnected.connect(self.on_device_disconnected)
        
        self.worker_thread.start()
        print("LISTENER: Started.")

    def on_log_message(self, message):
        if not self.log_dialog:
            self.log_dialog = QDialog(self)
            self.log_dialog.setWindowTitle("Connection Log")
            layout = QVBoxLayout()
            self.log_textbox = QTextEdit()
            self.log_textbox.setReadOnly(True)
            self.log_textbox.setFont(LOG_FONT)
            layout.addWidget(self.log_textbox)
            self.log_dialog.setLayout(layout)
            self.center_toplevel(self.log_dialog, 500, 300)
            self.log_dialog.setModal(True)
            self.log_dialog.show()
        
        if self.log_textbox:
            self.log_textbox.append(message)
            self.log_textbox.verticalScrollBar().setValue(self.log_textbox.verticalScrollBar().maximum())

    def on_connection_successful(self, device_name, all_info, preloaded_apps, preloaded_files_data):
        print("MAIN: Success.")
        if self.log_dialog:
            self.log_dialog.accept()
            self.log_dialog = None
        
        self.setup_main_ui()
        
        self.status_label.setText(f"Status: Connected to {device_name}")
        self.menubar.setDisabled(False)
        self.device_menu.setDisabled(False)

        self.on_device_info_updated(self.logic.get_formatted_device_info(all_info))
        self.on_file_list_updated(*preloaded_files_data)
        self.on_app_list_updated(preloaded_apps, None)
        
        self.after(100, lambda: self.logic._update_status_afc(self,
            "(AFC2)" if self.logic.is_jailbroken else "(AFC)",
            "green" if self.logic.is_jailbroken else "yellow"))
        
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self.setMinimumSize(800, 600)

    def on_connection_failed(self, error_message):
        print("MAIN: Failed.")
        if self.log_dialog:
            self.log_dialog.reject()
            self.log_dialog = None
        
        if "cancelled" not in error_message.lower():
            QMessageBox.critical(self, "Failed", error_message)
        
        if self.worker_thread:
            self.logic.stop_all_activity()
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
        
        self.device_menu.setDisabled(True)
        self.setup_waiting_ui()
        self.center_window(400, 200)
        self.setMinimumSize(400, 200)
        self.start_device_listener()

    def setup_menubar(self):
        self.menubar = self.menuBar()
        
        file_menu = self.menubar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.device_menu = self.menubar.addMenu("Device")
        self.device_menu.setDisabled(True)
        
        ss_action = QAction("Take Screenshot...", self)
        ss_action.triggered.connect(self.on_take_screenshot)
        self.device_menu.addAction(ss_action)
        
        bat_action = QAction("Get Battery Info", self)
        bat_action.triggered.connect(lambda: self.logic.run_in_thread(self.logic.get_battery_info))
        self.device_menu.addAction(bat_action)
        
        self.device_menu.addSeparator()
        
        reboot_action = QAction("Reboot Device...", self)
        reboot_action.triggered.connect(self.on_reboot_device)
        self.device_menu.addAction(reboot_action)
        
        shutdown_action = QAction("Shutdown Device...", self)
        shutdown_action.triggered.connect(self.on_shutdown_device)
        self.device_menu.addAction(shutdown_action)
        
        self.device_menu.addSeparator()
        
        recovery_action = QAction("Enter Recovery Mode...", self)
        recovery_action.triggered.connect(self.on_enter_recovery)
        self.device_menu.addAction(recovery_action)

    def setup_main_ui(self):
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        main_layout = QVBoxLayout()
        self.main_widget.setLayout(main_layout)
        
        self.font = MAIN_FONT
        
        top = QFrame()
        top_layout = QHBoxLayout()
        top.setLayout(top_layout)
        top.setFixedHeight(50)
        
        self.status_label = QLabel("Status: ...")
        self.status_label.setFont(self.font)
        top_layout.addWidget(self.status_label, 1)
        
        self.credits_btn = QPushButton("Credits")
        self.credits_btn.setFont(self.font)
        self.credits_btn.setStyleSheet("background-color: transparent; color: gray;")
        self.credits_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.credits_btn.clicked.connect(self.show_credits)
        top_layout.addWidget(self.credits_btn)
        
        main_layout.addWidget(top)
        
        self.tab_view = QTabWidget()
        self.tab_view.setFont(self.font)
        main_layout.addWidget(self.tab_view)
        
        self.tab_info = QWidget()
        self.tab_files = QWidget()
        self.tab_apps = QWidget()
        self.tab_syslog = QWidget()

        self.tab_view.addTab(self.tab_info, "Info")
        self.tab_view.addTab(self.tab_files, "Files")
        self.tab_view.addTab(self.tab_apps, "Apps")
        self.tab_view.addTab(self.tab_syslog, "Syslog")
        
        self.setup_info_tab(self.tab_info)
        self.setup_files_tab(self.tab_files)
        self.setup_apps_tab(self.tab_apps)
        self.setup_syslog_tab(self.tab_syslog)

    def setup_info_tab(self, tab):
        layout = QVBoxLayout()
        tab.setLayout(layout)
        self.info_btn = QPushButton("Refresh Info")
        self.info_btn.setFont(self.font)
        self.info_btn.clicked.connect(lambda: self.logic.run_in_thread(self.logic.refresh_device_info))
        layout.addWidget(self.info_btn)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(MONO_FONT)
        layout.addWidget(self.info_text)

    def on_device_info_updated(self, formatted_info):
        self.info_text.setText(formatted_info)

    def setup_files_tab(self, tab):
        layout = QVBoxLayout()
        tab.setLayout(layout)
        nav = QFrame(); nav_layout = QHBoxLayout(); nav.setLayout(nav_layout)
        nav_layout.addWidget(QLabel("Path:"))
        self.path_entry = QLineEdit()
        self.path_entry.setFont(MONO_FONT)
        self.path_entry.returnPressed.connect(self.on_file_path_entered)
        nav_layout.addWidget(self.path_entry, 1)
        self.go_up_btn = QPushButton("Up")
        self.go_up_btn.setFont(self.font)
        self.go_up_btn.clicked.connect(self.on_file_go_up)
        nav_layout.addWidget(self.go_up_btn)
        layout.addWidget(nav)
        
        self.file_list_widget = QListWidget()
        self.file_list_widget.setFont(LIST_FONT)
        self.file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        layout.addWidget(self.file_list_widget)
        
        act_frame = QFrame(); act_layout = QHBoxLayout(); act_frame.setLayout(act_layout)
        self.upload_btn = QPushButton("Upload..."); self.upload_btn.setFont(self.font); self.upload_btn.clicked.connect(self.on_file_upload)
        act_layout.addWidget(self.upload_btn)
        self.download_btn = QPushButton("Download..."); self.download_btn.setFont(self.font); self.download_btn.clicked.connect(self.on_file_download)
        act_layout.addWidget(self.download_btn)
        act_layout.addStretch()
        layout.addWidget(act_frame)

    def on_file_path_entered(self):
        path = self.path_entry.text()
        if self.logic: self.logic.run_in_thread(self.logic.fetch_file_list, path)
            
    def on_file_go_up(self):
        current = self.logic.current_path.rstrip('/')
        if current == "/" or (not self.logic.is_jailbroken and current == ""): return
        p = os.path.dirname(self.logic.current_path).replace("\\", "/")
        if self.logic: self.logic.run_in_thread(self.logic.fetch_file_list, p)

    def on_file_double_clicked(self, item):
        text = item.text()
        if text.startswith("[FOLDER] "):
            name = text.replace("[FOLDER] ", "")
            p = os.path.join(self.logic.current_path, name).replace("\\", "/")
            if self.logic: self.logic.run_in_thread(self.logic.fetch_file_list, p)

    def on_file_list_updated(self, folders, files, error):
        self.file_list_widget.clear()
        if error:
            item = QListWidgetItem(f"Error: {error}"); item.setForeground(QColor("red")); self.file_list_widget.addItem(item); return
        for f in sorted(folders, key=str.lower):
            item = QListWidgetItem(f); item.setForeground(QColor("#87CEFA")); self.file_list_widget.addItem(item)
        for f in sorted(files, key=str.lower):
            self.file_list_widget.addItem(f)
        self.path_entry.setText(self.logic.current_path)

    def on_file_upload(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select File(s) to Upload")
        if not paths: return
        if self.logic: self.logic.run_in_thread(self.logic.upload_files, paths, self.logic.current_path)

    def on_file_download(self):
        items = self.file_list_widget.selectedItems()
        if not items: self.on_action_error("Download", "No files selected."); return
        to_dl = [item.text() for item in items if not item.text().startswith("[FOLDER]")]
        if not to_dl: self.on_action_error("Download", "Please select files, not folders."); return
        save_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Save To")
        if not save_dir: return
        if self.logic: self.logic.run_in_thread(self.logic.download_files, to_dl, save_dir)

    def setup_apps_tab(self, tab):
        layout = QVBoxLayout(); tab.setLayout(layout)
        btn_frame = QFrame(); btn_layout = QHBoxLayout(); btn_frame.setLayout(btn_layout)
        
        self.apps_btn = QPushButton("Refresh App List"); self.apps_btn.setFont(self.font)
        self.apps_btn.clicked.connect(lambda: self.logic.run_in_thread(self.logic.fetch_app_list))
        btn_layout.addWidget(self.apps_btn)
        
        self.install_btn = QPushButton("Install .ipa..."); self.install_btn.setFont(self.font)
        self.install_btn.setObjectName("InstallBtn"); self.install_btn.clicked.connect(self.on_app_install)
        btn_layout.addWidget(self.install_btn); btn_layout.addStretch(); layout.addWidget(btn_frame)
        
        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        self.app_grid_widget = QWidget(); self.app_grid_layout = QGridLayout()
        self.app_grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.app_grid_widget.setLayout(self.app_grid_layout)
        scroll_area.setWidget(self.app_grid_widget)
        
        tab.installEventFilter(self)

    def eventFilter(self, source, event):
        if source == self.tab_view.widget(2) and event.type() == QEvent.Type.Resize:
            if self.logic and self.logic.apps_cache:
                print("DEBUG: App tab resized, recalculating grid...")
                self._update_app_grid(source, self.logic.apps_cache, None)
        return super().eventFilter(source, event)

    def on_app_list_updated(self, apps_data, error):
        self._update_app_grid(self.tab_view.widget(2), apps_data, error)

    def _update_app_grid(self, app_tab, apps_data, error, force_recalc=False):
        if not hasattr(self, 'app_grid_layout') or not self.app_grid_layout: return
        
        while self.app_grid_layout.count():
            item = self.app_grid_layout.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()
        
        for c in range(self.app_grid_layout.columnCount()):
            self.app_grid_layout.setColumnMinimumWidth(c, 0); self.app_grid_layout.setColumnStretch(c, 0)
            
        if error: self.app_grid_layout.addWidget(QLabel(f"Error listing apps:\n{error}"), 0, 0); return
        if not apps_data: self.app_grid_layout.addWidget(QLabel("No applications found."), 0, 0); return

        apps_data.sort(key=lambda x: x[0].lower())
        
        parent_width = self.app_grid_widget.width()
        if parent_width <= 10: parent_width = app_tab.width() - 30; print(f"DEBUG: Grid fallback width: {parent_width}")

        item_width = 110; parent_width = max(item_width, parent_width)
        cols = max(1, int(parent_width / item_width))
        print(f"DEBUG: Grid calculated {cols} columns.")

        for c in range(cols): self.app_grid_layout.setColumnStretch(c, 1) # Equal stretch

        for i, (name, version, app_type, bundle_id) in enumerate(apps_data):
            row, col = i // cols, i % cols
            
            app_frame = QFrame(); app_frame.setObjectName("AppFrame"); app_frame.setFixedSize(100, 120)
            app_frame_layout = QVBoxLayout(); app_frame_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            app_frame.setLayout(app_frame_layout)

            icon_placeholder = QLabel(); icon_placeholder.setFixedSize(60, 60); icon_placeholder.setStyleSheet("background-color: gray; border-radius: 10px;")
            app_frame_layout.addWidget(icon_placeholder)

            name_label = QLabel(name); name_label.setFont(APP_GRID_FONT); name_label.setWordWrap(True); name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            app_frame_layout.addWidget(name_label)
            
            app_frame.setProperty("bundle_id", bundle_id); app_frame.setProperty("app_name", name)
            app_frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            app_frame.customContextMenuRequested.connect(self.show_app_menu)

            self.app_grid_layout.addWidget(app_frame, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        
        self.app_grid_layout.setRowStretch(self.app_grid_layout.rowCount(), 1)


    def show_app_menu(self, pos):
        sender = self.sender()
        if not sender: return
        bundle_id = sender.property("bundle_id"); app_name = sender.property("app_name")
        
        menu = QMenu(self)
        
        menu.addAction("Explore Documents", lambda: self.logic.run_in_thread(self.logic.explore_app_documents, bundle_id))
        menu.addAction("Export IPA (WIP)", lambda: self.on_action_error("TODO", "Export IPA not implemented."))
        menu.addAction("Export Backup (WIP)", lambda: self.on_action_error("TODO", "Export Backup not implemented."))
        menu.addAction("Import Backup (WIP)", lambda: self.on_action_error("TODO", "Import Backup not implemented."))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self.on_app_uninstall(bundle_id, app_name))
        
        menu.exec(sender.mapToGlobal(pos))
    
    def on_app_install(self):
        ipa_path, _ = QFileDialog.getOpenFileName(self, "Select .ipa file", "", "IPA Files (*.ipa)")
        if not ipa_path: return
        if QMessageBox.question(self, "Confirm Install", f"Install {os.path.basename(ipa_path)}?") == QMessageBox.StandardButton.Yes:
            if self.logic: self.logic.run_in_thread(self.logic.install_app, ipa_path)

    def on_app_uninstall(self, bundle_id, app_name):
        if QMessageBox.question(self, "Confirm Uninstall", f"Uninstall '{app_name}'?") == QMessageBox.StandardButton.Yes:
            if "com.apple." in bundle_id:
                if QMessageBox.warning(self, "System App", f"'{app_name}' looks like a system app.\nProceed anyway?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                    return
            if self.logic: self.logic.run_in_thread(self.logic.uninstall_app, bundle_id, app_name)

    def setup_syslog_tab(self, tab):
        layout = QVBoxLayout(); tab.setLayout(layout)
        self.syslog_btn = QPushButton("Start Syslog"); self.syslog_btn.setFont(self.font)
        self.syslog_btn.clicked.connect(self.on_toggle_syslog)
        layout.addWidget(self.syslog_btn)
        self.syslog_text = QTextEdit(); self.syslog_text.setReadOnly(True); self.syslog_text.setFont(LOG_FONT)
        layout.addWidget(self.syslog_text)

    def on_toggle_syslog(self):
        if not self.logic: return
        if self.logic.syslog_thread and self.logic.syslog_thread.is_alive():
            self.logic.stop_syslog()
        else:
            self.syslog_text.clear(); self.logic.start_syslog(); self.syslog_btn.setText("Stop Syslog (Running...)")

    def on_syslog_message(self, message):
        sb = self.syslog_text.verticalScrollBar()
        at_bottom = (sb.value() == sb.maximum())
        self.syslog_text.append(message)
        if at_bottom:
            sb.setValue(sb.maximum())

    def on_syslog_stopped(self):
        self.syslog_btn.setText("Start Syslog")
    
    def on_action_finished(self, title, message):
        QMessageBox.information(self, title, message)
        self.status_label.setText(f"{message.splitlines()[0]}")
        
    def on_action_error(self, title, message):
        QMessageBox.warning(self, title, message)
        self.status_label.setText(f"Error: {title}")

    def on_device_disconnected(self, reason):
        print(f"MAIN: Device disconnected ({reason}), resetting UI.")
        self.on_connection_failed(f"Device disconnected: {reason}")
        
    def show_credits(self):
        QMessageBox.information(self, "PyAFC Credits",
                            "Developer: https://github.com/ZodaciOS\n"
                            "Source Code: https://github.com/ZodaciOS/PyAFC\n\n"
                            "Please star the repo and follow me thanks")

    def on_take_screenshot(self):
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot As...", filter="PNG Image (*.png)")
        if not save_path: return
        if not save_path.endswith(".png"): save_path += ".png"
        if self.logic: self.logic.run_in_thread(self.logic.take_screenshot, save_path)

    def on_reboot_device(self):
        if QMessageBox.question(self, "Confirm Reboot", "Are you sure you want to reboot the device?") == QMessageBox.StandardButton.Yes:
            if self.logic: self.logic.run_in_thread(self.logic.reboot_device)
            
    def on_shutdown_device(self):
        if QMessageBox.question(self, "Confirm Shutdown", "Are you sure you want to shut down the device?") == QMessageBox.StandardButton.Yes:
            if self.logic: self.logic.run_in_thread(self.logic.shutdown_device)

    def on_enter_recovery(self):
        if QMessageBox.warning(self, "!!! WARNING !!!",
                               "This will put your device into Recovery Mode.\n"
                               "You must restore it with iTunes/Finder to use it again.\n\n"
                               "ARE YOU ABSOLUTELY SURE?",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.logic: self.logic.run_in_thread(self.logic.enter_recovery)

    def closeEvent(self, event):
         print("MAIN: Closing...")
         if self.worker_thread:
             self.logic.stop_all_activity()
             self.worker_thread.quit()
             self.worker_thread.wait(1000)
         event.accept()

if __name__ == "__main__":
    if sys.platform == "win32":
        try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
        except Exception: pass
    
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    
    window = PyAFCGui()
    window.show()
    sys.exit(app.exec())
