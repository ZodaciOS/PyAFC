import tkinter as tk
from tkinter import filedialog, messagebox
from pymobiledevice3.services.installation_proxy import InstallationProxyService
import os

class AppLogic:
    def __init__(self, app):
        self.app = app
        self.client = None

    def list_applications(self):
        if not self.client: return
        self.app.app_listbox.delete(0, tk.END)
        self.app.app_listbox.insert(tk.END, "Loading... This may take a moment.")
        
        try:
            with InstallationProxyService(self.client) as ip:
                apps = ip.get_apps(app_type=None)
            
            self.app.app_listbox.delete(0, tk.END)
            if not apps:
                self.app.app_listbox.insert(tk.END, "No applications found.")
                return

            app_list = []
            for bundle_id, info in apps.items():
                app_name = info.get('CFBundleDisplayName', 'Unknown App')
                app_version = info.get('CFBundleShortVersionString', 'N/A')
                app_type = info.get('ApplicationType', 'User')
                app_list.append(f"{app_name} (v{app_version}) - [{app_type}] - {bundle_id}")
            
            for app_str in sorted(app_list, key=str.lower):
                self.app.app_listbox.insert(tk.END, app_str)
                if "[System]" in app_str:
                    self.app.app_listbox.itemconfig(tk.END, {'fg': '#AAAAAA'})
        except Exception as e:
            self.app.app_listbox.delete(0, tk.END)
            self.app.app_listbox.insert(tk.END, "Error listing applications.")
            messagebox.showerror("App List Error", f"Could not list applications: {e}")

    def install_app(self):
        if not self.client: return

        ipa_path = filedialog.askopenfilename(title="Select .ipa file to install", filetypes=[("IPA files", "*.ipa")])
        if not ipa_path: return

        if not messagebox.askyesno("Confirm Installation", f"Are you sure you want to install this .ipa?\n\n{os.path.basename(ipa_path)}"):
            return

        self.app.status_label.configure(text="Status: Installing .ipa...", text_color="yellow")
        try:
            with InstallationProxyService(self.client) as ip:
                ip.install(ipa_path)
            
            messagebox.showinfo("Install Complete", "Application installed successfully.")
            self.app.status_label.configure(text="Status: Install complete.", text_color="green")
            self.list_applications()
        except Exception as e:
            messagebox.showerror("Install Error", f"Could not install .ipa: {e}")
            self.app.status_label.configure(text="Status: Install failed.", text_color="red")

    def uninstall_apps(self):
        if not self.client: return
        
        selected_indices = self.app.app_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select one or more applications to uninstall.")
            return

        bundle_ids_to_uninstall = []
        app_names = []
        for i in selected_indices:
            app_str = self.app.app_listbox.get(i)
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

        self.app.status_label.configure(text="Status: Uninstalling...", text_color="yellow")
        try:
            with InstallationProxyService(self.client) as ip:
                for bundle_id in bundle_ids_to_uninstall:
                    ip.uninstall(bundle_id)
            
            messagebox.showinfo("Uninstall Complete", "Application(s) uninstalled successfully.")
            self.app.status_label.configure(text="Status: Uninstall complete.", text_color="green")
            self.list_applications()
        except Exception as e:
            messagebox.showerror("Uninstall Error", f"Could not uninstall app: {e}")
            self.app.status_label.configure(text="Status: Uninstall failed.", text_color="red")
