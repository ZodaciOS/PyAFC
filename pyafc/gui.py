import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from .core import DeviceCore
from .file_logic import FileLogic
from .app_logic import AppLogic
from .utils import run_in_thread

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PyAFCGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("PyAFC v1.0")
        self.geometry("750x600")

        self.core = DeviceCore(self)
        self.file_logic = FileLogic(self)
        self.app_logic = AppLogic(self)

        top_frame = ctk.CTkFrame(self, height=50)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        self.connect_btn = ctk.CTkButton(top_frame, text="Connect to Device", 
                                         command=lambda: run_in_thread(self.core.connect_device, self.file_logic, self.app_logic))
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
                                      command=lambda: run_in_thread(self.core.get_device_info), 
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
        self.path_entry.bind("<Return>", lambda e: run_in_thread(self.file_logic.browse_to_path, self.path_entry.get()))
        
        self.go_up_btn = ctk.CTkButton(file_nav_frame, text="Up (..)", width=50, 
                                       command=lambda: run_in_thread(self.file_logic.go_up_directory), 
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
        self.file_listbox.bind("<Double-Button-1>", lambda e: self.file_logic.on_file_double_click(e))
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_selection)

        file_action_frame = ctk.CTkFrame(tab)
        file_action_frame.pack(fill=tk.X, padx=10, pady=5)

        self.upload_btn = ctk.CTkButton(file_action_frame, text="Upload File(s)...", 
                                        command=lambda: run_in_thread(self.file_logic.upload_files), 
                                        state=tk.DISABLED)
        self.upload_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.download_btn = ctk.CTkButton(file_action_frame, text="Download Selected...", 
                                          command=lambda: run_in_thread(self.file_logic.download_files), 
                                          state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=10, pady=10)

    def setup_apps_tab(self, tab):
        app_btn_frame = ctk.CTkFrame(tab)
        app_btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.apps_btn = ctk.CTkButton(app_btn_frame, text="List Installed Applications", 
                                      command=lambda: run_in_thread(self.app_logic.list_applications), 
                                      state=tk.DISABLED)
        self.apps_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.install_btn = ctk.CTkButton(app_btn_frame, text="Install .ipa...", fg_color="green", 
                                         command=lambda: run_in_thread(self.app_logic.install_app), 
                                         state=tk.DISABLED)
        self.install_btn.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.uninstall_btn = ctk.CTkButton(app_btn_frame, text="Uninstall Selected", fg_color="#D32F2F", hover_color="#B71C1C", 
                                           command=lambda: run_in_thread(self.app_logic.uninstall_apps), 
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
