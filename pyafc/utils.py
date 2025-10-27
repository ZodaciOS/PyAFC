import threading

def run_in_thread(func, *args):
    def wrapper():
        threading.Thread(target=func, args=args, daemon=True).start()
    return wrapper
