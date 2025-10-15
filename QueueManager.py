import queue
import threading
import subprocess

task_queue = queue.Queue()
is_running = False

def worker():
    global is_running
    is_running = True
    while not task_queue.empty():
        task = task_queue.get()
        script_name = task["script"]
        params = task["params"]
        print(f"🚀 Running {script_name} with {params}")
        try:
            subprocess.run(["python", f"{script_name}.py"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Error running {script_name}: {e}")
        task_queue.task_done()
    is_running = False

def add_to_queue(script_name, params):
    task_queue.put({"script": script_name, "params": params})
    if not is_running:
        threading.Thread(target=worker, daemon=True).start()
        print(f"✅ Queued {script_name}")
