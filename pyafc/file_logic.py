import tkinter as tk
from tkinter import filedialog, messagebox
from pymobiledevice3.services.afc import AfcService, AfcError
import os
from .utils import run_in_thread

class FileLogic:
    def __init__(self, app):
        self.app = app
        self.client = None
        self.afc = None
        self.current_path = "/"
        self.is_jailbroken = False

    def start_afc_service(self):
        try:
            self.afc = AfcService(self.client)
            try:
                self.afc.listdir("/")
                self.is_jailbroken = True
                self.current_path = "/"
                new_status = self.app.status_label.cget("text") + " (AFC2 Root)"
                self.app.status_label.configure(text=new_status, text_color="green")
            except AfcError:
                self.is_jailbroken = False
                self.current_path = "/var/mobile/Media"
                new_status = self.app.status_label.cget("text") + " (Jailed AFC)"
                self.app.status_label.configure(text=new_status, text_color="yellow")
            
            self.browse_to_path(self.current_path)
        except Exception as e:
            messagebox.showerror("AFC Error", f"Could not start AFC service: {e}")

    def browse_to_path(self, path=None):
        if not self.afc: return
        if path: self.current_path = path
        
        self.app.path_entry.delete(0, tk.END)
        self.app.path_entry.insert(0, self.current_path)
        
        try:
            items = self.afc.listdir(self.current_path)
            self.app.file_listbox.delete(0, tk.END)
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
                self.app.file_listbox.insert(tk.END, folder)
                self.app.file_listbox.itemconfig(tk.END, {'fg': '#00AFFF'})
            for file in sorted(files, key=str.lower):
                self.app.file_listbox.insert(tk.END, file)
        except Exception as e:
            self.app.file_listbox.delete(0, tk.END)
            self.app.file_listbox.insert(tk.END, f"Error: {e}")

    def on_file_double_click(self, event=None):
        try:
            selected_item = self.app.file_listbox.get(self.app.file_listbox.curselection()[0])
            if selected_item.startswith("[FOLDER] "):
                folder_name = selected_item.replace("[FOLDER] ", "")
                new_path = os.path.join(self.current_path, folder_name).replace("\\", "/")
                run_in_thread(self.browse_to_path, new_path)()
        except IndexError:
            pass

    def go_up_directory(self):
        if self.current_path == "/" or (not self.is_jailbroken and self.current_path == "/var/mobile/Media"):
            return
        new_path = os.path.dirname(self.current_path).replace("\\", "/")
        self.browse_to_path(new_path)

    def upload_files(self):
        if not self.afc: return
        
        pc_file_paths = filedialog.askopenfilenames(title="Select File(s) to Upload")
        if not pc_file_paths: return

        for pc_file_path in pc_file_paths:
            filename = os.path.basename(pc_file_path)
            device_dest_path = os.path.join(self.current_path, filename).replace("\\", "/")
            try:
                self.app.status_label.configure(text=f"Status: Uploading {filename}...", text_color="yellow")
                self.afc.push(pc_file_path, device_dest_path)
            except Exception as e:
                messagebox.showerror("Upload Error", f"Could not upload {filename}: {e}")
                self.app.status_label.configure(text="Status: Upload failed", text_color="red")
                return
        
        messagebox.showinfo("Upload Complete", f"Successfully uploaded {len(pc_file_paths)} file(s).")
        self.app.status_label.configure(text="Status: Upload complete.", text_color="green")
        self.browse_to_path()

    def download_files(self):
        if not self.afc: return
        
        selected_indices = self.app.file_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select one or more files to download.")
            return

        pc_save_directory = filedialog.askdirectory(title="Select Folder to Save Files")
        if not pc_save_directory: return

        files_to_download = []
        for i in selected_indices:
            filename = self.app.file_listbox.get(i)
            if not filename.startswith("[FOLDER] "):
                files_to_download.append(filename)
        
        if not files_to_download:
            messagebox.showwarning("No Files Selected", "Please select files, not folders, to download.")
            return

        for filename in files_to_download:
            device_source_path = os.path.join(self.current_path, filename).replace("\\", "/")
            pc_save_path = os.path.join(pc_save_directory, filename)
            try:
                self.app.status_label.configure(text=f"Status: Downloading {filename}...", text_color="yellow")
                self.afc.pull(device_source_path, pc_save_path)
            except Exception as e:
                messagebox.showerror("Download Error", f"Could not download {filename}: {e}")
                self.app.status_label.configure(text="Status: Download failed", text_color="red")
                return
        
        messagebox.showinfo("Download Complete", f"Successfully downloaded {len(files_to_download)} file(s).")
        self.app.status_label.configure(text="Status: Download complete.", text_color="green")
