import sys
import customtkinter as ctk
from .gui import PyAFCGui

def main():
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass 
            
    app = PyAFCGui()
    app.mainloop()

if __name__ == "__main__":
    main()
