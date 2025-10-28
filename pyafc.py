import tkinter as tk
from tkinter import filedialog, messagebox, Menu
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
from pymobiledevice3.usbmux import list_devices
import threading
import json
import os
import sys
import time
import base64
import stat
from PIL import Image, ImageTk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

LARGE_FONT = ("Segoe UI", 24, "bold")
MAIN_FONT = ("Segoe UI", 13)
MONO_FONT = ("Consolas", 12)
LIST_FONT = ("Segoe UI", 11)
LOG_FONT = ("Consolas", 10)
APP_GRID_FONT = ("Segoe UI", 10)
LINK_FONT = ("Segoe UI", 12, "underline")

def json_bytes_handler(obj):
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return repr(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

class DeviceLogic:
    def __init__(self):
        self.client = None
        self.afc = None
        self.current_path = "/"
        self.is_jailbroken = False
        self.apps_cache = []
        self.initial_files_cache = ([], [], None)
        self.syslog_thread = None
        self.stop_syslog_event = threading.Event()

    def run_in_thread(self, func, *args):
        def wrapper():
            threading.Thread(target=func, args=args, daemon=True).start()
        return wrapper

    def connect_device(self, app, log_func, success_callback, failure_callback):
        print("LOGIC: connect_device function started")
        client_instance = None
        device_name = "Unknown Device"
        all_values = None
        preloaded_apps = []
        preloaded_files = ([], [], None)

        try:
            log_func("Attempting connection via USB...")
            devices = list_devices()
            target_udid = devices[0].serial if devices else None
            if not target_udid:
                raise PyMobileDevice3Exception("No device found by usbmux.")

            client_instance = create_using_usbmux(serial=target_udid)
            log_func(f"Connection successful to {target_udid}, client object created.")

            log_func("Waiting for connection to stabilize...")
            time.sleep(1)

            log_func("Attempting to fetch device info...")
            try:
                all_values = client_instance.get_value(None)
                if not all_values or not isinstance(all_values, dict):
                    error_msg = f"get_value(None) returned invalid data: {all_values!r}"
                    raise PyMobileDevice3Exception(error_msg)
                device_name = all_values.get("DeviceName", None)
                if device_name is None or device_name == {} or not isinstance(device_name, str):
                     error_msg = f"DeviceName missing or invalid: {device_name!r}"
                     raise PyMobileDevice3Exception(error_msg)
                log_func(f"Got device info. Name: {device_name}")
                self.client = client_instance
            except (PyMobileDevice3Exception, MissingValue if MissingValue else PyMobileDevice3Exception) as get_value_error:
                log_func(f"ERROR: Failed get values: {get_value_error}")
                app.after(0, lambda err=get_value_error: failure_callback(f"Connected but failed info.\nPairing issue?\n\nError: {err}"))
                if client_instance:
                    try:
                        client_instance.close()
                    except Exception as ce:
                        print(f"LOGIC: Close error 1: {ce}")
                return
            
            log_func("Attempting to mount Developer Image...")
            try:
                with MounterService(self.client) as mounter:
                    mounter.mount_developer_image()
                log_func("Developer Image mounted successfully.")
            except Exception as mount_error:
                log_func(f"WARNING: Failed to mount Developer Image: {mount_error}")
                log_func("Device actions (Screenshot, Reboot) may fail if Developer Mode is not enabled or image is missing.")

            log_func("Starting AFC service...")
            self.start_afc_service(app, log_func)
            if not self.afc:
                 app.after(0, lambda: failure_callback("Failed AFC service start."))
                 return

            log_func(f"Fetching initial file list for {self.current_path}...")
            preloaded_files = self._get_file_list_sync(self.current_path)
            folders, files, error = preloaded_files
            if error:
                log_func(f"Warning: Error fetching initial files ({self.current_path}): {error}")
                if self.current_path != "/":
                    log_func("Attempting fallback to '/'...")
                    self.current_path = "/"
                    preloaded_files = self._get_file_list_sync(self.current_path)
                    folders, files, error = preloaded_files
                    if error:
                        log_func(f"Warning: Fallback path also failed: {error}")
                        self.initial_files_cache = ([], [], error)
                    else:
                        log_func("Fallback path successful.")
                        self.initial_files_cache = preloaded_files
                else:
                    self.initial_files_cache = ([], [], error)
            else:
                log_func(f"Fetched initial files: {len(folders)} folders, {len(files)} files.")
                self.initial_files_cache = preloaded_files


            log_func("Fetching application list...")
            preloaded_apps, app_error = self._get_app_list_sync()
            self.apps_cache = preloaded_apps
            if app_error:
                log_func(f"Warning: Error fetching apps: {app_error}")
            else:
                log_func(f"Fetched {len(preloaded_apps)} applications.")

            log_func("Pre-loading complete. Connection setup successful!")
            app.after(0, lambda name=device_name, info=all_values, apps=self.apps_cache, files_data=self.initial_files_cache: \
                      success_callback(name, info, apps, files_data))

        except Exception as e:
            log_func(f"ERROR: Connect process failed: {e}")
            app.after(0, lambda err=e: failure_callback(f"Could not connect.\nTrusted?\niTunes/AMDS running?\n\nError: {err}"))
            if client_instance and not self.client:
                try:
                    client_instance.close()
                except Exception as ce:
                    print(f"LOGIC: Close error 2: {ce}")

    def get_device_info(self, all_info=None):
        if not self.client and not all_info:
            return "Error: Not connected/no info."
        try:
            if all_info is None:
                if not self.client:
                    raise PyMobileDevice3Exception("Client unavailable")
                all_info = self.client.get_value(None)
                if not all_info:
                    raise PyMobileDevice3Exception("Empty info")
            info = []
            keys = [
                ("DeviceName","Name"), ("ProductType","Model"),("HardwareModel","HW Model"),
                ("ProductName","OS"), ("ProductVersion","Version"), ("BuildVersion","Build"),
                ("UniqueDeviceID","UDID"), ("SerialNumber","Serial"), ("CPUArchitecture","CPU"),
                ("WiFiAddress","WiFi"), ("BluetoothAddress","BT"), ("TimeZone","Zone"),
                ("ActivationState","Act State")
            ]
            for k, l in keys:
                v = all_info.get(k, "N/A")
                fv = repr(v)
                try:
                    fv = json.dumps(v, default=json_bytes_handler).strip('"')
                except TypeError:
                    pass
                info.append(f"{l}: {fv}")
            return "\n".join(info)
        except Exception as e:
            return f"Error fetching info:\n{e}"

    def start_afc_service(self, app, log_func):
        if not self.client:
            log_func("ERROR: AFC start fail, no client!")
            self.afc = None
            return
        log_func("Attempting AfcService...")
        try:
            self.afc = AfcService(self.client)
            log_func("AfcService created.")
            time.sleep(0.2)
            try:
                log_func("Checking JB (access '/private')...")
                self.afc.listdir("/private")
                log_func("Jailbroken (AFC2).")
                self.is_jailbroken = True
                self.current_path = "/"
            except PyMobileDevice3Exception:
                log_func("Jailed (AFC).")
                self.is_jailbroken = False
                self.current_path = "/"
                log_func(f"Set initial jailed path to: {self.current_path} (will remap to Media)")
            log_func("AFC ready.")
        except Exception as e:
            log_func(f"ERROR: AFC start fail: {e}")
            self.afc = None

    def _update_status_afc(self, app, suffix, color):
        try:
            if hasattr(app, 'status_label') and app.status_label.winfo_exists():
                curr = app.status_label.cget("text").split(" (")[0]
                if suffix not in curr:
                    app.status_label.configure(text=f"{curr} {suffix}", text_color=color)
        except tk.TclError:
            pass

    def _get_file_list_sync(self, path_to_list):
        folders, files, error_msg = [], [], None
        if not self.afc:
            return folders, files, "AFC service not ready"
        try:
            print(f"LOGIC (Sync): Attempting AFC listdir('{path_to_list}')...")
            items = self.afc.listdir(path_to_list)
            print(f"LOGIC (Sync): listdir found {len(items)} items")
            for item in items:
                if item in ('.', '..'): continue
                fp = os.path.join(path_to_list, item).replace("\\", "/")
                is_dir = False
                try:
                    info = self.afc.stat(fp)
                    if hasattr(info, 'st_ifmt') and stat.S_ISDIR(info.st_ifmt):
                        is_dir = True
                except (PyMobileDevice3Exception, AttributeError):
                    try:
                        self.afc.listdir(fp)
                        is_dir = True
                        print(f"DEBUG: stat failed, but listdir succeeded for {item}")
                    except PyMobileDevice3Exception:
                        is_dir = False
                
                if is_dir:
                    folders.append(f"[FOLDER] {item}")
                else:
                    files.append(item)
        except Exception as e:
            print(f"LOGIC (Sync): listdir FAILED: {e}")
            error_msg = e
        return folders, files, error_msg


    def browse_to_path(self, app, path=None):
        print(f"LOGIC: browse: {path if path else self.current_path}")
        if not self.afc:
            print("LOGIC: AFC not ready")
            app.after(0, lambda: self._update_file_listbox(app, [], [], "AFC not ready"))
            return
        if path:
            self.current_path = path
        try:
            if hasattr(app, 'path_entry') and app.path_entry.winfo_exists():
                 app.path_entry.delete(0, tk.END)
                 app.path_entry.insert(0, self.current_path)
        except tk.TclError:
            pass

        def _list_dir_task():
            folders, files, error = self._get_file_list_sync(self.current_path)
            app.after(0, lambda flds=folders, fls=files, err=error: self._update_file_listbox(app, flds, fls, err))

        threading.Thread(target=_list_dir_task, daemon=True).start()

    def _update_file_listbox(self, app, folders, files, error=None):
        try:
            if hasattr(app, 'file_listbox') and app.file_listbox.winfo_exists():
                lb = app.file_listbox
                lb.delete(0, tk.END)
                if error:
                    lb.insert(tk.END, f"Error: {error}")
                    lb.itemconfig(tk.END, {'fg': 'red'})
                    return
                for f in sorted(folders, key=str.lower):
                    lb.insert(tk.END, f)
                    lb.itemconfig(tk.END, {'fg': '#87CEFA'})
                for f in sorted(files, key=str.lower):
                    lb.insert(tk.END, f)
        except tk.TclError:
            pass

    def on_file_double_click(self, app, event=None):
        try:
            if not hasattr(app, 'file_listbox') or not app.file_listbox.winfo_exists():
                print("DEBUG DBLCLICK: Listbox not found")
                return
            sel = app.file_listbox.curselection()
            if not sel:
                print("DEBUG DBLCLICK: No selection")
                return

            item_index = sel[0]
            item = app.file_listbox.get(item_index)
            print(f"DEBUG DBLCLICK: Item='{item}' at index {item_index}")

            if item.startswith("[FOLDER] "):
                print("DEBUG DBLCLICK: Identified as Folder")
                name = item.replace("[FOLDER] ", "")
                p = os.path.join(self.current_path, name).replace("\\", "/")
                print(f"DEBUG DBLCLICK: Calling browse_to_path with: {p}")
                self.browse_to_path(app, p)
            else:
                 print("DEBUG DBLCLICK: Not a folder")
        except IndexError:
            print("DEBUG DBLCLICK: IndexError")
            pass
        except tk.TclError as e:
            print(f"DEBUG DBLCLICK: TclError ({e})")
            pass
        except Exception as e:
            print(f"DEBUG DBLCLICK: Unexpected error: {e}")

    def go_up_directory(self, app):
        current_check_path = self.current_path.rstrip('/')
        if current_check_path == "/" or \
           (not self.is_jailbroken and current_check_path == ""):
            print(f"DEBUG GO UP: Already at root or media root ({self.current_path})")
            return
        p = os.path.dirname(self.current_path).replace("\\", "/")
        print(f"DEBUG GO UP: New path: {p}")
        self.browse_to_path(app, p)

    def _update_status_label(self, app, text, color):
         app.after(0, lambda t=text, c=color: app.status_label.configure(text=t, text_color=c) if hasattr(app, 'status_label') and app.status_label.winfo_exists() else None)

    def upload_files(self, app):
        if not self.afc: return
        paths = filedialog.askopenfilenames(title="Upload")
        if not paths: return
        def _task():
            try:
                for p in paths:
                    fn = os.path.basename(p)
                    dp = os.path.join(self.current_path, fn).replace("\\", "/")
                    self._update_status_label(app, f"Uploading {fn}...", "yellow")
                    self.afc.push(p, dp)
                app.after(0, lambda: messagebox.showinfo("Done", f"Uploaded {len(paths)} file(s)."))
                self._update_status_label(app, "Status: Upload complete.", "green")
                self.browse_to_path(app)
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Upload failed: {err}"))
                self._update_status_label(app, "Upload failed", "red")
        threading.Thread(target=_task, daemon=True).start()

    def download_files(self, app):
        if not self.afc: return
        if not hasattr(app, 'file_listbox') or not app.file_listbox.winfo_exists(): return
        sel = app.file_listbox.curselection()
        if not sel:
            app.after(0, lambda: messagebox.showwarning("Select", "Select file(s)."))
            return
        save_dir = filedialog.askdirectory(title="Save To")
        if not save_dir: return
        to_dl = []
        try:
            for i in sel:
                fn = app.file_listbox.get(i)
                if not fn.startswith("[FOLDER] "):
                    to_dl.append(fn)
        except tk.TclError:
            app.after(0, lambda: messagebox.showerror("Error", "Selection changed."))
            return
        if not to_dl:
            app.after(0, lambda: messagebox.showwarning("Select", "Select file(s), not folders."))
            return
        def _task():
            try:
                for fn in to_dl:
                    sp = os.path.join(self.current_path, fn).replace("\\", "/")
                    pp = os.path.join(save_dir, fn)
                    self._update_status_label(app, f"Downloading {fn}...", "yellow")
                    self.afc.pull(sp, pp)
                app.after(0, lambda n=len(to_dl): messagebox.showinfo("Done", f"Downloaded {n} file(s)."))
                self._update_status_label(app, "Download complete.", "green")
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Download failed: {err}"))
                self._update_status_label(app, "Download failed", "red")
        threading.Thread(target=_task, daemon=True).start()

    def _get_app_list_sync(self):
        apps_data = []
        error_msg = None
        if not self.client:
            return apps_data, "Client not connected"
        try:
            print("LOGIC (Sync): Starting InstallationProxyService...")
            with InstallationProxyService(self.client) as ip:
                print("LOGIC (Sync): Fetching apps...")
                apps = ip.get_apps()
                print(f"LOGIC (Sync): Fetched {len(apps) if apps else 0} apps.")
            if apps:
                for bundle_id, info in apps.items():
                    name = info.get('CFBundleDisplayName', bundle_id)
                    version = info.get('CFBundleShortVersionString', 'N/A')
                    app_type = info.get('ApplicationType', 'User')
                    apps_data.append((name, version, app_type, bundle_id))
            print("LOGIC (Sync): App list processing complete.")
        except Exception as e:
            error_msg = e
            print(f"LOGIC (Sync): Error fetching apps: {e}")
        return apps_data, error_msg

    def list_applications(self, app, use_cache=False):
        print("DEBUG: list_applications called (use_cache={use_cache})")
        if not self.client:
            print("DEBUG: No client")
            return

        try:
            app_tab = app.tab_view.tab("Apps")
            if hasattr(app, 'app_grid_frame') and app.app_grid_frame.winfo_exists():
                for widget in app.app_grid_frame.winfo_children(): widget.destroy()
                loading_label = ctk.CTkLabel(app.app_grid_frame, text="Loading...", font=MAIN_FONT, text_color="gray")
                loading_label.grid(row=0, column=0, padx=10, pady=10)
                app.update_idletasks()
            else:
                print("DEBUG: app_grid_frame not found")
                return
        except tk.TclError:
            print("DEBUG: TclError clearing app grid")
            return

        if use_cache and self.apps_cache:
            print("DEBUG: Using cached app data.")
            self._update_app_grid(app, app_tab, self.apps_cache)
        else:
            def _fetch_apps_task():
                print("DEBUG: _fetch_apps_task started (background)")
                apps_data, error_msg = self._get_app_list_sync()
                self.apps_cache = apps_data

                if error_msg:
                    app.after(0, lambda error=error_msg, tab=app_tab: self._update_app_grid_error(app, tab, error))
                else:
                    app.after(0, lambda data=apps_data, tab=app_tab: self._update_app_grid(app, tab, data))
                print("DEBUG: _fetch_apps_task finished.")

            threading.Thread(target=_fetch_apps_task, daemon=True).start()

    def _update_app_grid(self, app, app_tab, apps_data):
        try:
            if hasattr(app, 'app_grid_frame') and app.app_grid_frame.winfo_exists():
                app_grid = app.app_grid_frame
                for widget in app_grid.winfo_children():
                    widget.destroy()
                for c in range(app_grid.grid_size()[0]):
                    app_grid.columnconfigure(c, weight=0, minsize=0)

                if not apps_data:
                    ctk.CTkLabel(app_grid, text="No applications found.", font=MAIN_FONT, text_color="gray").grid(row=0, column=0, padx=10, pady=10)
                    return

                apps_data.sort(key=lambda x: x[0].lower())
                app_tab.update_idletasks()
                app_grid.after(50, lambda ag=app_grid, at=app_tab, ad=apps_data: self._configure_and_populate_grid(app, ag, at, ad))

            else:
                print("DEBUG ERROR: app_grid_frame missing")
        except tk.TclError as e:
            print(f"DEBUG: TclError grid update start: {e}")
            pass
        except Exception as e:
             print(f"DEBUG: Unexpected error grid update start: {e}")

    def _configure_and_populate_grid(self, app, app_grid, app_tab, apps_data):
        try:
            if not app_grid.winfo_exists():
                return

            parent_width = app_grid.winfo_width()
            if parent_width <= 10:
                 parent_width = app_tab.winfo_width() - 30
                 print(f"DEBUG: Grid fallback width: {parent_width}")
            
            item_width_estimate = 110
            parent_width = max(item_width_estimate, parent_width)
            cols = max(1, int(parent_width / item_width_estimate))

            print(f"DEBUG: Grid Parent Width: {parent_width}")
            print(f"DEBUG: Item Width Estimate: {item_width_estimate}")
            print(f"DEBUG: Calculated Columns: {cols}")

            if cols > 0:
                for c in range(cols):
                    app_grid.columnconfigure(c, weight=1, minsize=item_width_estimate - 10)

            for i, (name, version, app_type, bundle_id) in enumerate(apps_data):
                row, col = i // cols, i % cols
                app_frame = ctk.CTkFrame(app_grid, width=100, height=120, corner_radius=5)
                app_frame.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
                app_frame.grid_propagate(False)
                icon_placeholder = ctk.CTkFrame(app_frame, width=60, height=60, fg_color="gray30", corner_radius=10)
                icon_placeholder.pack(pady=(10, 5))
                name_label = ctk.CTkLabel(app_frame, text=name, font=APP_GRID_FONT, wraplength=90)
                name_label.pack(pady=(0, 10), padx=5, fill="x")
                for widget in [app_frame, icon_placeholder, name_label]:
                     widget.bind("<Button-3>", lambda event, b_id=bundle_id, a_name=name: app.show_app_menu(event, b_id, a_name))

        except tk.TclError as e:
            print(f"DEBUG: TclError grid config/populate: {e}")
            pass
        except Exception as e:
             print(f"DEBUG: Unexpected error grid config/populate: {e}")


    def _update_app_grid_error(self, app, app_tab, error):
        try:
            if hasattr(app, 'app_grid_frame') and app.app_grid_frame.winfo_exists():
                for widget in app.app_grid_frame.winfo_children():
                    widget.destroy()
                ctk.CTkLabel(app.app_grid_frame, text=f"Error listing apps:\n{error}", font=MAIN_FONT, text_color="red").grid(row=0, column=0, padx=10, pady=10)
                messagebox.showerror("App Error", f"Could not list apps: {error}")
        except tk.TclError:
            pass

    def install_app(self, app):
        if not self.client: return
        ipa=filedialog.askopenfilename(title="Select .ipa", filetypes=[("IPA","*.ipa")])
        if not ipa: return
        if not messagebox.askyesno("Confirm", f"Install {os.path.basename(ipa)}?"): return
        def _task():
            try:
                 self._update_status_label(app, "Installing...", "yellow")
                 with InstallationProxyService(self.client) as ip:
                     ip.install(ipa)
                 app.after(0, lambda: messagebox.showinfo("Done", "Success."))
                 self._update_status_label(app, "Install complete.", "green")
                 self.list_applications(app)
            except Exception as e:
                 app.after(0, lambda err=e: messagebox.showerror("Error", f"Install failed: {err}"))
                 self._update_status_label(app, "Install failed", "red")
        threading.Thread(target=_task, daemon=True).start()

    def uninstall_app_action(self, app, bundle_id, app_name):
        if not messagebox.askyesno("Confirm", f"Uninstall '{app_name}'?"): return
        if "com.apple." in bundle_id:
             if not messagebox.askyesno("Warning", f"'{app_name}' might be system app.\nProceed anyway?"): return
        def _task():
            err = False
            try:
                self._update_status_label(app, f"Uninstalling {app_name}...", "yellow")
                with InstallationProxyService(self.client) as ip:
                    ip.uninstall(bundle_id)
            except Exception as e:
                err = True
                app.after(0, lambda bid=bundle_id, error=e: messagebox.showerror("Error", f"Failed to uninstall {bid}:\n{error}"))
            if not err:
                app.after(0, lambda name=app_name: messagebox.showinfo("Done", f"'{name}' uninstalled."))
            self._update_status_label(app, "Uninstall finished.", "green" if not err else "red")
            self.list_applications(app)
        threading.Thread(target=_task, daemon=True).start()

    def explore_app_documents(self, app, bundle_id):
        print(f"LOGIC: explore docs for {bundle_id}")
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        def _task():
            contents, error = [], None
            try:
                print("LOGIC: Starting HouseArrest...")
                with HouseArrestService(self.client, bundle_id=bundle_id, connection_type='DOCUMENTS') as ha:
                    print("LOGIC: Listing /Documents...")
                    items = ha.listdir('/Documents')
                    print(f"LOGIC: Found {len(items)} items.")
                    contents = sorted(items)
            except Exception as e:
                error = f"Could not explore:\n{e}"
                print(f"LOGIC: Explore error: {e}")
            if error:
                app.after(0, lambda err=error: messagebox.showerror("Error", err))
            elif not contents:
                app.after(0, lambda: messagebox.showinfo("Explore", f"App: {bundle_id}\n\nDocuments empty/inaccessible."))
            else:
                display = f"App: {bundle_id}\n\nDocuments:\n- " + "\n- ".join(contents)
                app.after(0, lambda txt=display: messagebox.showinfo("Explore", txt))
        threading.Thread(target=_task, daemon=True).start()

    def take_screenshot(self, app):
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        save_path = filedialog.asksaveasfilename(title="Save Screenshot As...", filetypes=[("PNG Image", "*.png")], defaultextension=".png")
        if not save_path:
            return
        
        def _task():
            self._update_status_label(app, "Taking screenshot...", "yellow")
            try:
                with ScreenshotService(self.client) as screenshoter:
                    screenshoter.save(save_path)
                app.after(0, lambda p=save_path: messagebox.showinfo("Success", f"Screenshot saved to:\n{p}"))
                self._update_status_label(app, "Screenshot saved.", "green")
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to take screenshot:\n{err}"))
                self._update_status_label(app, "Screenshot failed.", "red")
        
        self.run_in_thread(_task)()

    def get_battery_info(self, app):
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        
        def _task():
            try:
                with DiagnosticsService(self.client) as diag:
                    info = diag.get_battery()
                
                level = info.get("BatteryCurrentCapacity", "N/A")
                status = info.get("BatteryChargeStatus", "N/A")
                msg = f"Battery Level: {level}%\nStatus: {status}"
                app.after(0, lambda m=msg: messagebox.showinfo("Battery Info", m))
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to get battery info:\n{err}"))
        
        self.run_in_thread(_task)()

    def reboot_device(self, app):
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        if not messagebox.askyesno("Confirm Reboot", "Are you sure you want to reboot the device?"):
            return
        
        def _task():
            self._update_status_label(app, "Sending reboot command...", "yellow")
            try:
                with DiagnosticsService(self.client) as diag:
                    diag.restart()
                app.after(0, lambda: messagebox.showinfo("Reboot", "Device is rebooting. App will reset."))
                app.after(1000, lambda: app._connection_failed("Device disconnected for reboot."))
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to reboot:\n{err}"))
        
        self.run_in_thread(_task)()

    def shutdown_device(self, app):
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        if not messagebox.askyesno("Confirm Shutdown", "Are you sure you want to shut down the device?"):
            return
        
        def _task():
            self._update_status_label(app, "Sending shutdown command...", "yellow")
            try:
                with DiagnosticsService(self.client) as diag:
                    diag.shutdown()
                app.after(0, lambda: messagebox.showinfo("Shutdown", "Device is powering off. App will reset."))
                app.after(1000, lambda: app._connection_failed("Device disconnected for shutdown."))
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to shutdown:\n{err}"))
        
        self.run_in_thread(_task)()

    def enter_recovery(self, app):
        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return
        if not messagebox.askyesno("!!! WARNING !!!",
                                   "This will put your device into Recovery Mode.\n"
                                   "You will NOT be able to use your device until you restore it with iTunes, Finder, or another tool.\n\n"
                                   "ARE YOU ABSOLUTELY SURE?", icon='warning'):
            return
        
        def _task():
            self._update_status_label(app, "Entering recovery mode...", "red")
            try:
                with DiagnosticsService(self.client) as diag:
                    diag.enter_recovery()
                app.after(0, lambda: messagebox.showinfo("Recovery", "Device entering recovery mode. App will reset."))
                app.after(1000, lambda: app._connection_failed("Device disconnected for recovery."))
            except Exception as e:
                app.after(0, lambda err=e: messagebox.showerror("Error", f"Failed to enter recovery:\n{err}"))
        
        self.run_in_thread(_task)()

    def toggle_syslog_stream(self, app):
        if self.syslog_thread and self.syslog_thread.is_alive():
            print("LOGIC: Stopping syslog stream...")
            self.stop_syslog_event.set()
            app.syslog_btn.configure(text="Start Syslog")
            return

        if not self.client:
            messagebox.showerror("Error", "Not connected.")
            return

        self.stop_syslog_event.clear()
        app.syslog_btn.configure(text="Stop Syslog (Running...)")

        def _stream_task():
            try:
                print("LOGIC: Starting syslog stream thread...")
                with SyslogService(self.client) as syslog:
                    for line in syslog.watch():
                        if self.stop_syslog_event.is_set():
                            print("LOGIC: Syslog stop event received.")
                            break
                        app.after(0, lambda l=line: app.append_to_syslog(l))
            except Exception as e:
                print(f"LOGIC: Syslog stream error: {e}")
                app.after(0, lambda err=e: app.append_to_syslog(f"\n--- SYSLOG ERROR: {err} ---\n"))
            finally:
                print("LOGIC: Syslog stream thread finished.")
                app.after(0, lambda: app.syslog_btn.configure(text="Start Syslog") if hasattr(app, 'syslog_btn') and app.syslog_btn.winfo_exists() else None)

        self.syslog_thread = threading.Thread(target=_stream_task, daemon=True)
        self.syslog_thread.start()


class PyAFCGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PyAFC v1.0")
        self.logic = DeviceLogic()
        self.device_listener_thread = None
        self.stop_listener = threading.Event()
        self.log_window = None
        self.log_textbox = None
        self.is_connecting = False
        
        self.menubar = Menu(self, font=MAIN_FONT, bg="#2B2B2B", fg="white", activebackground="#36719F", activeforeground="white")
        self.config(menu=self.menubar)

        file_menu = Menu(self.menubar, tearoff=0, font=MAIN_FONT, bg="#2B2B2B", fg="white", activebackground="#36719F", activeforeground="white")
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Exit", command=self.on_closing)

        self.device_menu = Menu(self.menubar, tearoff=0, font=MAIN_FONT, bg="#2B2B2B", fg="white", activebackground="#36719F", activeforeground="white")
        self.menubar.add_cascade(label="Device", menu=self.device_menu, state="disabled")
        
        self.device_menu.add_command(label="Take Screenshot...", command=lambda: self.logic.run_in_thread(self.logic.take_screenshot, self))
        self.device_menu.add_command(label="Get Battery Info", command=lambda: self.logic.run_in_thread(self.logic.get_battery_info, self))
        self.device_menu.add_separator()
        self.device_menu.add_command(label="Reboot Device...", command=lambda: self.logic.run_in_thread(self.logic.reboot_device, self))
        self.device_menu.add_command(label="Shutdown Device...", command=lambda: self.logic.run_in_thread(self.logic.shutdown_device, self))
        self.device_menu.add_separator()
        self.device_menu.add_command(label="Enter Recovery Mode...", command=lambda: self.logic.run_in_thread(self.logic.enter_recovery, self))
        
        self.setup_waiting_ui()
        self.center_window(400, 200)
        self.start_device_listener()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def center_window(self, width, height):
        screen_w=self.winfo_screenwidth()
        screen_h=self.winfo_screenheight()
        x=(screen_w/2)-(width/2)
        y=(screen_h/2)-(height/2)
        self.geometry(f'{width}x{height}+{int(x)}+{int(y)}')
        self.update_idletasks()

    def center_toplevel(self, top, w, h):
         self.update_idletasks()
         main_x=self.winfo_x()
         main_y=self.winfo_y()
         main_w=self.winfo_width()
         main_h=self.winfo_height()
         x=main_x+(main_w/2)-(w/2)
         y=main_y+(main_h/2)-(h/2)
         top.geometry(f'{w}x{h}+{int(x)}+{int(y)}')
         top.update_idletasks()

    def setup_waiting_ui(self):
        for w in self.winfo_children():
            if not isinstance(w, tk.Menu):
                w.destroy()
        self.resizable(False, False)
        self.status_frame=ctk.CTkFrame(self, fg_color="transparent")
        self.status_frame.pack(expand=True, fill="both", padx=20, pady=20)
        self.wait_label_main=ctk.CTkLabel(self.status_frame, text="Connect device.", font=LARGE_FONT)
        self.wait_label_main.pack(pady=(10, 10))
        self.wait_label_status=ctk.CTkLabel(self.status_frame, text="Waiting...", font=MAIN_FONT, text_color="gray")
        self.wait_label_status.pack(pady=0)
        self.help_button = ctk.CTkButton(self.status_frame, text="Device not connecting?",
                                         font=LINK_FONT, fg_color="transparent", text_color="#87CEFA",
                                         hover_color="gray20", command=self.show_connection_help)
        self.help_button.pack(pady=(10, 10)) # Corrected line

    def show_connection_help(self):
        help_text = (
            "- Ensure your iPhone has the computer trusted.\n\n"
            "- Ensure iTunes or Apple Devices (Microsoft Store) is installed.\n\n"
            "- Try a different device and see if it works properly.\n\n"
            "- Try a different cable and see if it works properly.\n\n"
            "- If none of these steps work, create an issue in our GitHub repo:\n"
            "  https://github.com/ZodaciOS/PyAFC/issues"
        )
        help_window = ctk.CTkToplevel(self)
        help_window.title("Connection Help")
        help_window.attributes("-topmost", True)
        label = ctk.CTkLabel(help_window, text=help_text, font=MAIN_FONT, justify=tk.LEFT)
        label.pack(expand=True, fill="both", padx=20, pady=20)
        self.center_toplevel(help_window, 450, 250)
        help_window.grab_set()

    def start_device_listener(self):
        if self.device_listener_thread and self.device_listener_thread.is_alive():
            return
        self.stop_listener.clear()
        self.is_connecting = False
        self.device_listener_thread = threading.Thread(target=self._listen_for_devices, daemon=True)
        self.device_listener_thread.start()
        print("LISTENER: Started.")

    def _listen_for_devices(self):
        while not self.stop_listener.is_set():
            if self.is_connecting:
                time.sleep(1)
                continue
            try:
                devices = list_devices()
                found = bool(devices)
                if found:
                    print(f"LISTENER: Found: {[d.serial for d in devices]}")
                    self.is_connecting = True
                    self.after(0, self._start_connection_process)
                    break
                else:
                     if hasattr(self,'wait_label_status') and self.wait_label_status.winfo_exists():
                         if self.wait_label_status.cget("text")!="Waiting...":
                             self.after(0, lambda: self.wait_label_status.configure(text="Waiting..."))
            except Exception as e:
                print(f"LISTENER Error: {e}")
                break
            time.sleep(3)
        print("LISTENER: Stopped.")

    def _start_connection_process(self):
        print("MAIN: Connecting...")
        if hasattr(self, 'status_frame') and self.status_frame.winfo_exists():
            self.status_frame.pack_forget()
        self.show_log_window()
        def log(msg):
            if self.log_window and self.log_window.winfo_exists() and self.log_textbox and self.log_textbox.winfo_exists():
                self.log_textbox.after(0, lambda m=msg: self._append_log_message(m))
            else:
                print(f"LOG (No Win): {msg}")
        threading.Thread(target=self.logic.connect_device, args=(self, log, self._connection_successful, self._connection_failed), daemon=True).start()

    def _append_log_message(self, message):
         try:
            if self.log_textbox and self.log_textbox.winfo_exists():
                self.log_textbox.configure(state=tk.NORMAL)
                self.log_textbox.insert(tk.END, message + "\n")
                self.log_textbox.configure(state=tk.DISABLED)
                self.log_textbox.see(tk.END)
         except tk.TclError:
             pass

    def show_log_window(self):
        if self.log_window is None or not self.log_window.winfo_exists():
            self.log_window=ctk.CTkToplevel(self)
            self.log_window.title("Log")
            w,h=500,300
            self.center_toplevel(self.log_window, w,h)
            self.log_window.resizable(True, True)
            self.log_window.attributes("-topmost", True)
            self.log_window.protocol("WM_DELETE_WINDOW", lambda: self._connection_failed("Cancelled."))
            self.log_textbox=ctk.CTkTextbox(self.log_window, wrap=tk.WORD, state=tk.DISABLED, font=LOG_FONT)
            self.log_textbox.pack(expand=True, fill="both", padx=10, pady=10)
        else:
            self.log_window.lift()

    def _connection_successful(self, device_name, all_device_info, preloaded_apps, preloaded_files_data):
        print("MAIN: Success.")
        self.is_connecting = False
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.protocol("WM_DELETE_WINDOW", self.log_window.destroy)
            self.log_window.destroy()
        self.log_window = None
        self.log_textbox = None

        try:
            self.state('zoomed')
            self.resizable(True, True)
        except tk.TclError:
            print("Warn: Maximize failed.")
            self.geometry("900x700")
            self.resizable(True, True)
        
        self.update_idletasks()
        self.after(50, lambda: self.setup_main_ui(device_name, all_device_info, preloaded_apps, preloaded_files_data))

    def _connection_failed(self, error_message):
        print("MAIN: Failed.")
        self.is_connecting = False
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.protocol("WM_DELETE_WINDOW", self.log_window.destroy)
            self.log_window.destroy()
        self.log_window = None
        self.log_textbox = None
        if "cancelled" not in error_message.lower():
            messagebox.showerror("Failed", error_message)
        
        self.menubar.entryconfig("Device", state="disabled")
        self.logic = DeviceLogic()
        self.setup_waiting_ui()
        self.center_window(400, 200)
        self.start_device_listener()

    def setup_main_ui(self, device_name, all_device_info, preloaded_apps, preloaded_files_data):
        for w in self.winfo_children():
            if not isinstance(w, tk.Menu):
                w.destroy()
        
        self.font = MAIN_FONT
        self.menubar.entryconfig("Device", state="normal")

        top=ctk.CTkFrame(self, height=50)
        top.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.status_label=ctk.CTkLabel(top, text=f"Status: Connected to {device_name}", text_color="green", font=self.font)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.credits_btn=ctk.CTkButton(top, text="Credits", width=60, fg_color="transparent", text_color="gray", font=self.font, command=self.show_credits)
        self.credits_btn.pack(side=tk.RIGHT, padx=10, pady=10)
        
        self.tab_view=ctk.CTkTabview(self)
        self.tab_view.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
        self.tab_view.add("Info")
        self.tab_view.add("Files")
        self.tab_view.add("Apps")
        self.tab_view.add("Syslog")
        
        self.setup_info_tab(self.tab_view.tab("Info"), all_device_info)
        self.setup_files_tab(self.tab_view.tab("Files"), preloaded_files_data)
        self.setup_apps_tab(self.tab_view.tab("Apps"), preloaded_apps)
        self.setup_syslog_tab(self.tab_view.tab("Syslog"))
        
        self.after(100, lambda: self.logic._update_status_afc(self,
            "(AFC2)" if self.logic.is_jailbroken else "(AFC)",
            "green" if self.logic.is_jailbroken else "yellow"))

    def setup_info_tab(self, tab, all_device_info):
        self.info_btn = ctk.CTkButton(tab, text="Refresh Info", font=self.font,
                                      command=lambda: self.logic.run_in_thread(self.update_info_tab))
        self.info_btn.pack(pady=10, padx=10, fill=tk.X)
        self.info_text = ctk.CTkTextbox(tab, wrap=tk.WORD, state=tk.DISABLED, font=MONO_FONT)
        self.info_text.pack(pady=(0, 10), padx=10, fill=tk.BOTH, expand=True)
        self.update_info_tab(all_device_info)

    def update_info_tab(self, info_to_display=None):
        formatted_info = self.logic.get_device_info(all_info=info_to_display)
        try:
            if hasattr(self, 'info_text') and self.info_text.winfo_exists():
                self.info_text.configure(state=tk.NORMAL)
                self.info_text.delete(1.0, tk.END)
                self.info_text.insert(tk.END, formatted_info)
                self.info_text.configure(state=tk.DISABLED)
        except tk.TclError:
            pass

    def setup_files_tab(self, tab, preloaded_files_data):
        nav=ctk.CTkFrame(tab)
        nav.pack(fill=tk.X, padx=10, pady=(5,0))
        ctk.CTkLabel(nav, text="Path:", font=self.font).pack(side=tk.LEFT, padx=(10, 5))
        self.path_entry=ctk.CTkEntry(nav, font=MONO_FONT)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10, padx=5)
        self.path_entry.bind("<Return>", lambda e: self.logic.browse_to_path(self, self.path_entry.get()))
        self.go_up_btn=ctk.CTkButton(nav, text="Up", width=40, font=self.font, command=lambda: self.logic.go_up_directory(self))
        self.go_up_btn.pack(side=tk.LEFT, padx=(0, 10), pady=10)
        list_frame=ctk.CTkFrame(tab)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.file_listbox=tk.Listbox(list_frame, height=15, selectmode=tk.EXTENDED, bg="#2B2B2B", fg="white", selectbackground="#36719F", selectforeground="white", activestyle="none", borderwidth=0, highlightthickness=0, font=LIST_FONT)
        scroll=ctk.CTkScrollbar(list_frame, command=self.file_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0,1))
        self.file_listbox.config(yscrollcommand=scroll.set)
        self.file_listbox.pack(fill=tk.BOTH, expand=True, pady=1, padx=(1,0))
        self.file_listbox.bind("<Double-Button-1>", lambda e: self.logic.on_file_double_click(self, e))
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_selection)
        act_frame=ctk.CTkFrame(tab)
        act_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.upload_btn=ctk.CTkButton(act_frame, text="Upload...", font=self.font, command=lambda: self.logic.upload_files(self))
        self.upload_btn.pack(side=tk.LEFT, padx=10, pady=10)
        self.download_btn=ctk.CTkButton(act_frame, text="Download...", font=self.font, command=lambda: self.logic.download_files(self), state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=(0, 10), pady=10)
        
        folders, files, error = preloaded_files_data
        self.logic._update_file_listbox(self, folders, files, error)
        if hasattr(self, 'path_entry') and self.path_entry.winfo_exists():
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, self.logic.current_path)

    def setup_apps_tab(self, tab, preloaded_apps):
        app_btn_frame = ctk.CTkFrame(tab)
        app_btn_frame.pack(fill=tk.X, padx=10, pady=(5,0))
        self.apps_btn = ctk.CTkButton(app_btn_frame, text="Refresh App List", font=self.font, command=lambda: self.logic.list_applications(self))
        self.apps_btn.pack(side=tk.LEFT, padx=10, pady=10)
        self.install_btn = ctk.CTkButton(app_btn_frame, text="Install .ipa...", fg_color="green", font=self.font, command=lambda: self.logic.install_app(self))
        self.install_btn.pack(side=tk.LEFT, padx=(0, 10), pady=10)
        self.app_grid_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.app_grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.app_grid_frame.grid_columnconfigure(0, weight=1)
        
        self.logic._update_app_grid(self, tab, preloaded_apps)

    def setup_syslog_tab(self, tab):
        self.syslog_btn = ctk.CTkButton(tab, text="Start Syslog", font=self.font,
                                      command=lambda: self.logic.toggle_syslog_stream(self))
        self.syslog_btn.pack(pady=10, padx=10, fill=tk.X)
        
        self.syslog_text = ctk.CTkTextbox(tab, wrap=tk.WORD, state=tk.DISABLED, font=LOG_FONT)
        self.syslog_text.pack(pady=(0, 10), padx=10, fill=tk.BOTH, expand=True)

    def append_to_syslog(self, message):
        try:
            if hasattr(self, 'syslog_text') and self.syslog_text.winfo_exists():
                self.syslog_text.configure(state=tk.NORMAL)
                self.syslog_text.insert(tk.END, message)
                self.syslog_text.configure(state=tk.DISABLED)
                if self.syslog_text.yview()[1] > 0.9:
                    self.syslog_text.see(tk.END)
        except tk.TclError:
            pass

    def show_app_menu(self, event, bundle_id, app_name):
        print(f"DEBUG: Right-clicked app: {app_name} ({bundle_id})")
        menu = Menu(self, tearoff=0, background="#2B2B2B", foreground="white", activebackground="#36719F", activeforeground="white", relief="flat", font=MAIN_FONT)
        menu.add_command(label="Explore Documents", command=lambda bid=bundle_id: self.logic.explore_app_documents(self, bid))
        menu.add_command(label="Export IPA", command=lambda: messagebox.showwarning("TODO", "Export IPA WIP.\nFairPlay DRM!"))
        menu.add_command(label="Export Backup", command=lambda: messagebox.showinfo("TODO", "Export Backup WIP."))
        menu.add_command(label="Import Backup", command=lambda: messagebox.showinfo("TODO", "Import Backup WIP."))
        menu.add_separator(background="gray50")
        menu.add_command(label="Uninstall", command=lambda bid=bundle_id, name=app_name: self.logic.uninstall_app_action(self, bid, name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_file_selection(self, event=None):
        try:
            if not hasattr(self, 'file_listbox') or not self.file_listbox.winfo_exists(): return
            sel = self.file_listbox.curselection(); enable = False
            if sel:
                for i in sel:
                    try: item = self.file_listbox.get(i)
                    except tk.TclError: continue
                    if not item.startswith("[FOLDER] "): enable = True; break
            if hasattr(self, 'download_btn') and self.download_btn.winfo_exists():
                self.download_btn.configure(state=tk.NORMAL if enable else tk.DISABLED)
        except tk.TclError:
             if hasattr(self, 'download_btn') and self.download_btn.winfo_exists():
                 self.download_btn.configure(state=tk.DISABLED)

    def show_credits(self):
        messagebox.showinfo("PyAFC Credits",
                            "Developer: https://github.com/ZodaciOS\n"
                            "Source Code: https://github.com/ZodaciOS/PyAFC\n\n"
                            "Please star the repo and follow me thanks")

    def on_closing(self):
         print("MAIN: Closing..."); self.stop_listener.set()
         if self.logic:
             self.logic.stop_syslog_event.set()
         if self.device_listener_thread and self.device_listener_thread.is_alive():
             self.device_listener_thread.join(timeout=1.0)
         if self.logic and self.logic.client:
             try:
                 self.logic.client.close()
                 print("MAIN: Closed lockdown client.")
             except Exception as close_err:
                 print(f"MAIN: Error closing client on exit: {close_err}")
         self.destroy()

if __name__ == "__main__":
    if sys.platform == "win32":
        try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
        except Exception: pass
    app = PyAFCGui()
    app.mainloop()
