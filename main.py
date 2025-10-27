# pyafc + all the files compiled into one.
# download it and run it ig
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.services.afc import AfcService, AfcError
from pymobiledevice3.services.installation_proxy import InstallationProxyService
import threading
import json
import os
import sys

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DeviceLogic:
    def __init__(self):
        self.client = None
        self.afc = None
        self.current_path = "/"
        self.is_jailbroken = False

    def run_in_thread(self, func, *args):
        def wrapper():
            threading.Thread(target=func, args=args, daemon=True).start()
        return wrapper

    def connect_device(self, app):
        try:
            app.status_label.configure(text="Status: Connecting...", text_color="yellow")
            self.client = LockdownClient()
            device_name = self.client.get_value("DeviceName", "Unknown Device")
            app.status_label.configure(text=f"Status: Connected to {device_name}", text_color="green")

            app.info_btn.configure(state=tk.NORMAL)
            app.apps_btn.configure(state=tk.NORMAL)
            app.upload_btn.configure(state=tk.NORMAL)
            app.go_up_btn.configure(state=tk.NORMAL)
            app.install_btn.configure(state=tk.NORMAL)
            
            self.start_afc_service(app)

        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to device.\nIs it plugged in and 'Trusted'?\n\nError: {e}")
            app.status_label.configure(text="Status: Connection Failed", text_color="red")
            app.disable_all_buttons()

    def get_device_info(self, app):
        if not self.client: return
        try:
            all_info = self.client.get_value(None)
            info_str = json.dumps(all_info, indent=4)
            
            app.info_text.configure(state=tk.NORMAL)
            app.info_text.delete(1.0, tk.END)
            app.info_text.insert(tk.END, info_str)
            app.info_text.configure(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Info Error", f"Could not get device info: {e}")

    def start_afc_service(self, app):
        try:
            self.afc = AfcService(self.client)
            try:
                self.afc.listdir("/")
                self.is_jailbroken = True
                self.current_path = "/"
                new_status = app.status_label.cget("text") + " (AFC2 Root)"
                app.status_label.configure(text=new_status, text_color="green")
            except AfcError:
                self.is_jailbroken = False
                self.current_path = "/var/mobile/Media"
                new_status = app.status_label.cget("text") + " (Jailed AFC)"
                app.status_label.configure(text=new_status, text_color="yellow")
            
            self.browse_to_path(app, self.current_path)
        except Exception as e:
            messagebox.showerror("AFC Error", f"Could not start AFC service: {e}")

    def browse_to_path(self, app, path=None):
        if not self.afc: return
        if path: self.current_path = path
        
        app.path_entry.delete(0, tk.END)
        app.path_entry.insert(0, self.current_path)
        
        try:
            items = self.afc.listdir(self.current_path)
            app.file_listbox.delete(0, tk.END)
            folders, files = [], []
            for item in items:
                if item in ('.', '..'): continue
                full_item_path = os.path.join(self.current_path, item).replace("\\", "/")
                try:
                    if self.afc.get_file_info(full_item_path).get('st_ifmt') == 'S_IFDIR':
                        folders.append(f"[FOLDER] {item}")
                    else:
                        files.append(item)
                except AfcError:
                    files.append(f"[???] {item}")
            
            for folder in sorted(folders, key=str.lower):
                app.file_listbox.insert(tk.END, folder)
                app.file_listbox.itemconfig(tk.END, {'fg': '#00AFFF'})
            for file in sorted(files, key=str.lower):
                app.file_listbox.insert(tk.END, file)
        except Exception as e:
            app.file_listbox.delete(0, tk.END)
            app.file_listbox.insert(tk.END, f"Error: {e}")

    def on_file_double_click(self, app, event=None):
        try:
            selected_item = app.file_listbox.get(app.file_listbox.curselection()[0])
            if selected_item.startswith("[FOLDER] "):
                folder_name = selected_item.replace("[FOLDER] ", "")
                new_path = os.path.join(self.current_path, folder_name).replace("\\", "/")
                self.run_in_thread(self.browse_to_path, app, new_path)()
        except IndexError:
            pass

    def go_up_directory(self, app):
        if self.current_path == "/" or (not self.is_jailbroken and self.current_path == "/var/mobile/Media"):
            return
        new_path = os.path.dirname(self.current_path).replace("\\", "/")
        self.browse_to_path(app, new_path)

    def upload_files(self, app):
        if not self.afc: return
        
        pc_file_paths = filedialog.askopenfilenames(title="Select File(s) to Upload")
        if not pc_file_paths: return

        for pc_file_path in pc_file_paths:
            filename = os.path.basename(pc_file_path)
            device_dest_path = os.path.join(self.current_path, filename).replace("\\", "/")
            try:
                app.status_label.configure(text=f"Status: Uploading {filename}...", text_color="yellow")
                self.afc.push(pc_file_path, device_dest_path)
            except Exception as e:
                messagebox.showerror("Upload Error", f"Could not upload {filename}: {e}")
                app.status_label.configure(text="Status: Upload failed", text_color="red")
                return
        
        messagebox.showinfo("Upload Complete", f"Successfully uploaded {len(pc_file_paths)} file(s).")
        app.status_label.configure(text="Status: Upload complete.", text_color="green")
        self.browse_to_path(app)

    def download_files(self, app):
        if not self.afc: return
        
        selected_indices = app.file_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select one or more files to download.")
            return

        pc_save_directory = filedialog.askdirectory(title="Select Folder to Save Files")
        if not pc_save_directory: return

        files_to_download = []
        for i in selected_indices:
            filename = app.file_listbox.get(i)
            if not filename.startswith("[FOLDER] "):
                files_to_download.append(filename)
        
        if not files_to_download:
            messagebox.showwarning("No Files Selected", "Please select files, not folders, to download.")
            return

        for filename in files_to_download:
            device_source_path = os.path.join(self.current_path, filename).replace("\\", "/")
            pc_save_path = os.path.join(pc_save_directory, filename)
            try:
                app.status_label.configure(text=f"Status: Downloading {filename}...", text_color="yellow")
                self.afc.pull(device_source_path, pc_save_path)
            except Exception as e:
                messagebox.showerror("Download Error", f"Could not download {filename}: {e}")
                app.status_label.configure(text="Status: Download failed", text_color="red")
                return
        
        messagebox.showinfo("Download Complete", f"Successfully downloaded {len(files_to_download)} file(s).")
        app.status_label.configure(text="Status: Download complete.", text_color="green")

    def list_applications(self, app):
        if not self.client: return
        app.app_listbox.delete(0, tk.END)
        app.app_listbox.insert(tk.END, "Loading... This may take a moment.")
        
        try:
            with InstallationProxyService(self.client) as ip:
                apps = ip.get_apps(app_type=None)
            
            app.app_listbox.delete(0, tk.END)
            if not apps:
                app.app_listbox.insert(tk.END, "No applications found.")
                return

            app_list = []
            for bundle_id, info in apps.items():
                app_name = info.get('CFBundleDisplayName', 'Unknown App')
                app_version = info.get('CFBundleShortVersionString', 'N/A')
                app_type = info.get('ApplicationType', 'User')
                app_list.append(f"{app_name} (v{app_version}) - [{app_type}] - {bundle_id}")
            
            for app_str in sorted(app_list, key=str.lower):
                app.app_listbox.insert(tk.END, app_str)
                if "[System]" in app_str:
                    app.app_listbox.itemconfig(tk.END, {'fg': '#AAAAAA'})
        except Exception as e:
            app.app_listbox.delete(0, tk.END)
            app.app_listbox.insert(tk.END, "Error listing applications.")
            messagebox.showerror("App List Error", f"Could not list applications: {e}")

    def install_app(self, app):
        if not self.client: return

        ipa_path = filedialog.askopenfilename(title="Select .ipa file to install", filetypes=[("IPA files", "*.ipa")])
        if not ipa_path: return

        if not messagebox.askyesno("Confirm Installation", f"Are you sure you want to install this .ipa?\n\n{os.path.basename(ipa_path)}"):
            return

        app.status_label.configure(text="Status: Installing .ipa...", text_color="yellow")
        try:
            with InstallationProxyService(self.client) as ip:
                ip.install(ipa_path)
            
            messagebox.showinfo("Install Complete", "Application installed successfully.")
            app.status_label.configure(text="Status: Install complete.", text_color="green")
            self.list_applications(app)
        except Exception as e:
            messagebox.showerror("Install Error", f"Could not install .ipa: {e}")
            app.status_label.configure(text="Status: Install failed.", text_color="red")

    def uninstall_apps(self, app):
        if not self.client: return
        
        selected_indices = app.app_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select one or more applications to uninstall.")
            return

        bundle_ids_to_uninstall = []
        app_names = []
        for i in selected_indices:
            app_str = app.app_listbox.get(i)
            try:
                bundle_id = app_str.split(" - ")[-1]
                app_name = app_str.split(" (v")[0]
                
                if "com.apple." in bundle_id and "[System]" in app_str:
                    messagebox.showwarning("Skipped", f"Cannot uninstall a core system app: {app_name}")
                    continue
                    
                bundle_ids_to_uninstall.append(bundle_id)
                app_names.append(app_name)
            except Exception:
                pass
        
        if not bundle_ids_to_uninstall:
            return

        if not messagebox.askyesno("Confirm Uninstall", f"Are you sure you want to uninstall these {len(app_names)} app(s)?\n\n- " + "\n- ".join(app_names)):
            return

        app.status_label.configure(text="Status: Uninstalling...", text_color="yellow")
        try:
            with InstallationProxyService(self.client) as ip:
                for bundle_id in bundle_ids_to_uninstall:
                    ip.uninstall(bundle_id)
            
            messagebox.showinfo("Uninstall Complete", "Application(s) uninstalled successfully.")
            app.status_label.configure(text="Status: Uninstall complete.", text_color="green")
            self.list_applications(app)
        except Exception as e:
            messagebox.showerror("Uninstall Error", f"Could not uninstall app: {e}")
            app.status_label.configure(text="Status: Uninstall failed.", text_color="red")

class PyAFCGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("PyAFC v1.0")
        self.geometry("750x600")

        self.logic = DeviceLogic()

        top_frame = ctk.CTkFrame(self, height=50)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        self.connect_btn = ctk.CTkButton(top_frame, text="Connect to Device", 
                                         command=lambda: self.logic.run_in_thread(self.logic.connect_device, self))
        self.connect_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.status_label = ctk.CTkLabel(top_frame, text="Status: Disconnected", text_color="gray")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        self.credits_btn = ctk.CTkButton(top_frame, text="Credits", width=60, fg_color="transparent", text_color="gray",
                                         command=self.show_credits)
        self.credits_btn.pack(side=tk.RIGHT, padx=10, pady=10)

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.tab_view.add("Device Info")
        self.tab_view.add("File Explorer")
        self.tab_view.add("Applications")

        self.setup_info_tab(self.tab_view.tab("Device Info"))
        self.setup_files_tab(self.tab_view.tab("File Explorer"))
        self.setup_apps_tab(self.tab_view.tab("Applications"))

    def setup_info_tab(self, tab):
        self.info_btn = ctk.CTkButton(tab, text="Get Device Info", 
                                      command=lambda: self.logic.run_in_thread(self.logic.get_device_info, self), 
                                      state=tk.DISABLED)
        self.info_btn.pack(pady=10, padx=10, fill=tk.X)
        
        self.info_text = ctk.CTkTextbox(tab, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 12))
        self.info_text.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

    def setup_files_tab(self, tab):
        file_nav_frame = ctk.CTkFrame(tab)
        file_nav_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ctk.CTkLabel(file_nav_frame, text="Path:").pack(side=tk.LEFT, padx=(10, 5))
        self.path_entry = ctk.CTkEntry(file_nav_frame, font=("Consolas", 12))
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10)
        self.path_entry.bind("<Return>", lambda e: self.logic.run_in_thread(self.logic.browse_to_path, self, self.path_entry.get()))
        
        self.go_up_btn = ctk.CTkButton(file_nav_frame, text="Up (..)", width=50, 
                                       command=lambda: self.logic.run_in_thread(self.logic.go_up_directory, self), 
                                       state=tk.DISABLED)
        self.go_up_btn.pack(side=tk.LEFT, padx=10, pady=10)

        file_list_frame = ctk.CTkFrame(tab)
        file_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.file_listbox = tk.Listbox(file_list_frame, 
                                        height=15, 
                                        selectmode=tk.EXTENDED,
                                        bg="#2B2B2B", 
                                        fg="white", 
                                        selectbackground="#1F6AA5", 
                                        selectforeground="white",
                                        activestyle="none",
                                        borderwidth=0, 
                                        highlightthickness=0,
                                        font=("Consolas", 11))
        
        file_scrollbar = ctk.CTkScrollbar(file_list_frame, command=self.file_listbox.yview)
        file_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=file_scrollbar.set)
        
        self.file_listbox.pack(fill=tk.BOTH, expand=True, pady=1, padx=1)
        self.file_listbox.bind("<Double-Button-1>", lambda e: self.logic.on_file_double_click(self, e))
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_selection)

        file_action_frame = ctk.CTkFrame(tab)
        file_action_frame.pack(fill=tk.X, padx=10, pady=5)

        self.upload_btn = ctk.CTkButton(file_action_frame, text="Upload File(s)...", 
                                        command=lambda: self.logic.run_in_thread(self.logic.upload_files, self), 
                                        state=tk.DISABLED)
        self.upload_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.download_btn = ctk.CTkButton(file_action_frame, text="Download Selected...", 
                                          command=lambda: self.logic.run_in_thread(self.logic.download_files, self), 
                                          state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=10, pady=10)

    def setup_apps_tab(self, tab):
        app_btn_frame = ctk.CTkFrame(tab)
        app_btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.apps_btn = ctk.CTkButton(app_btn_frame, text="List Installed Applications", 
                                      command=lambda: self.logic.run_in_thread(self.logic.list_applications, self), 
                                      state=tk.DISABLED)
        self.apps_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.install_btn = ctk.CTkButton(app_btn_frame, text="Install .ipa...", fg_color="green", 
                                         command=lambda: self.logic.run_in_thread(self.logic.install_app, self), 
                                         state=tk.DISABLED)
        self.install_btn.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.uninstall_btn = ctk.CTkButton(app_btn_frame, text="Uninstall Selected", fg_color="#D32F2F", hover_color="#B71C1C", 
                                           command=lambda: self.logic.run_in_thread(self.logic.uninstall_apps, self), 
                                           state=tk.DISABLED)
        self.uninstall_btn.pack(side=tk.RIGHT, padx=10, pady=10)

        app_list_frame = ctk.CTkFrame(tab)
        app_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.app_listbox = tk.Listbox(app_list_frame, 
                                       selectmode=tk.EXTENDED,
                                       bg="#2B2B2B", 
                                       fg="white", 
                                       selectbackground="#1F6AA5", 
                                       selectforeground="white",
                                       activestyle="none",
                                       borderwidth=0, 
                                       highlightthickness=0,
                                       font=("Consolas", 11))
        
        app_scrollbar = ctk.CTkScrollbar(app_list_frame, command=self.app_listbox.yview)
        app_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app_listbox.config(yscrollcommand=app_scrollbar.set)
        
        self.app_listbox.pack(fill=tk.BOTH, expand=True, pady=1, padx=1)
        self.app_listbox.bind("<<ListboxSelect>>", self.on_app_selection)

    def on_file_selection(self, event=None):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            self.download_btn.configure(state=tk.DISABLED)
            return
        
        is_file_selected = False
        for i in selected_indices:
            if not self.file_listbox.get(i).startswith("[FOLDER] "):
                is_file_selected = True
                break
        
        if is_file_selected:
            self.download_btn.configure(state=tk.NORMAL)
        else:
            self.download_btn.configure(state=tk.DISABLED)

    def on_app_selection(self, event=None):
        if self.app_listbox.curselection():
            self.uninstall_btn.configure(state=tk.NORMAL)
        else:
            self.uninstall_btn.configure(state=tk.DISABLED)

    def disable_all_buttons(self):
        self.info_btn.configure(state=tk.DISABLED)
        self.apps_btn.configure(state=tk.DISABLED)
        self.upload_btn.configure(state=tk.DISABLED)
        self.download_btn.configure(state=tk.DISABLED)
        self.go_up_btn.configure(state=tk.DISABLED)
        self.install_btn.configure(state=tk.DISABLED)
        self.uninstall_btn.configure(state=tk.DISABLED)
    
    def show_credits(self):
        messagebox.showinfo("PyAFC Credits", 
                            "Developer: https://github.com/ZodaciOS\n"
                            "Source Code: https://github.com/ZodaciOS/PyAFC\n\n"
                            "Please star the repo and follow me thanks")

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass 
            
    app = PyAFCGui()
    app.mainloop()
