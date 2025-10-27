import tkinter as tk
from tkinter import messagebox
from pymobiledevice3.lockdown import LockdownClient
import json
from .utils import run_in_thread

class DeviceCore:
    def __init__(self, app):
        self.app = app
        self.client = None

    def connect_device(self, file_logic, app_logic):
        try:
            self.app.status_label.configure(text="Status: Connecting...", text_color="yellow")
            self.client = LockdownClient()
            device_name = self.client.get_value("DeviceName", "Unknown Device")
            self.app.status_label.configure(text=f"Status: Connected to {device_name}", text_color="green")
            
            file_logic.client = self.client
            app_logic.client = self.client

            self.app.info_btn.configure(state=tk.NORMAL)
            self.app.apps_btn.configure(state=tk.NORMAL)
            self.app.upload_btn.configure(state=tk.NORMAL)
            self.app.go_up_btn.configure(state=tk.NORMAL)
            self.app.install_btn.configure(state=tk.NORMAL)
            
            run_in_thread(file_logic.start_afc_service)()

        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to device.\nIs it plugged in and 'Trusted'?\n\nError: {e}")
            self.app.status_label.configure(text="Status: Connection Failed", text_color="red")
            self.app.disable_all_buttons()

    def get_device_info(self):
        if not self.client: return
        try:
            all_info = self.client.get_value(None)
            info_str = json.dumps(all_info, indent=4)
            
            self.app.info_text.configure(state=tk.NORMAL)
            self.app.info_text.delete(1.0, tk.END)
            self.app.info_text.insert(tk.END, info_str)
            self.app.info_text.configure(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Info Error", f"Could not get device info: {e}")
