import os
import sys
import time
import queue
import socket
import threading
import statistics
import collections
import tkinter as tk

import cv2
import mediapipe as mp
from plyer import notification
import pystray
from PIL import Image, ImageDraw

# ---------------- Settings ----------------
CAMERA_INDEX = 0                 # 0 means default camera
FRAME_W, FRAME_H = 320, 240      # small frames = low CPU
CHECK_INTERVAL = 0.3             # checks about 3 times per second
CALIBRATION_SAMPLES = 15         # baseline readings used for calibration
BUFFER_SIZE = 5                  # median of last 5 readings avoids false alerts

# Slouch is detected when ANY of these three signals passes its limit
SLOUCH_DROP = 0.08               # head sinks toward shoulders (8% drop in nose-shoulder ratio)
LEAN_GROW = 0.10                 # shoulders look 10% wider = you leaned toward the screen
HEAD_DOWN = 0.15                 # nose moved down by 15% of your shoulder width

SLOUCH_SECONDS = 3               # continuous slouching time before alert
NOTIFY_COOLDOWN = 20             # seconds between alerts
SHOW_NUMBERS = False             # True = show live numbers in the box (only for tuning)
# ------------------------------------------

stop_event = threading.Event()
pause_event = threading.Event()          # set = paused
recalibrate_event = threading.Event()
ui_queue = queue.Queue()                 # commands from tray / second launch -> UI thread
status = {"text": "Starting..."}
tray_ref = {"icon": None}

# ---- Single instance guard ----
# A second launch asks the running copy to show its control box, then exits.
# This is also how a user brings back a hidden box: just open the app again.
_lock = socket.socket()
try:
    _lock.bind(("127.0.0.1", 49731))
    _lock.listen(5)
except OSError:
    try:
        socket.create_connection(("127.0.0.1", 49731), timeout=1).close()
    except Exception:
        pass
    sys.exit(0)


def _instance_server():
    while True:
        try:
            conn, _ = _lock.accept()
            conn.close()
            ui_queue.put("show")
        except Exception:
            break


BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE, "pose_landmarker_lite.task")

BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode


def set_status(text):
    status["text"] = text


def notify(title, msg):
    """Windows notification via plyer; falls back to the tray icon balloon."""
    try:
        if notification.notify is not None:
            notification.notify(title=title, message=msg,
                            app_name="Posture Detector", timeout=4)
        return
    except Exception:
        pass
    try:
        if tray_ref["icon"] is not None:
            tray_ref["icon"].notify(msg, title)
    except Exception:
        pass

"""Currently I disable the value of calculation of this part as it becomes annoying/distracting for user"""
# ---------------- Posture measurement ----------------
def pose_metrics(result, w, h):
    """Returns the numbers we track for one frame, or None if you aren't clearly visible."""
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks[0]
    nose, ls, rs = lm[0], lm[11], lm[12]

    if min(ls.visibility, rs.visibility) < 0.4:
        return None

    dx = (ls.x - rs.x) * w
    dy = (ls.y - rs.y) * h
    shoulder_px = (dx ** 2 + dy ** 2) ** 0.5
    if shoulder_px < 10:
        return None

    shoulder_y = (ls.y + rs.y) / 2 * h
    nose_y = nose.y * h
    return {
        "ratio": (shoulder_y - nose_y) / shoulder_px,   # nose-to-shoulder distance / shoulder width
        "dist": shoulder_px / w,                        # shoulder width as a fraction of the frame
        "nose": nose.y,                                 # nose height in the frame (0 top, 1 bottom)
        "aspect": h / w,
    }
"""The calculation is very simple it takes the distance from nose to mid point of the distance between 
both shoulders divided by the the shoulder width, this gives a ratio,ratio helps
to make the calculation more reliable the the normal distance calculation  """

def summarize(items):
    """Median of each number over a list of readings."""
    return {k: statistics.median(m[k] for m in items) for k in items[0]}


def slouch_signals(cur, base):
    drop = (base["ratio"] - cur["ratio"]) / base["ratio"]           # head sinking toward shoulders
    lean = cur["dist"] / base["dist"] - 1                           # leaning toward the camera
    head = (cur["nose"] - base["nose"]) * cur["aspect"] / base["dist"]  # head lower in the frame
    return drop, lean, head


def read_pose(cap, landmarker):
    if cap is None or not cap.isOpened():
        return None
    ok, frame = cap.read()
    if not ok:
        return None
    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)    # OpenCV is BGR, MediaPipe wants RGB
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    return pose_metrics(landmarker.detect(img), w, h)
"""RGB means each pixel stores its colors in this order: Red, Green, Blue.
OpenCv uses BGR, while Meadiapipe requires RGB"""

def open_camera():
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(CAMERA_INDEX, backend)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    for _ in range(15):          # skip dark frames while exposure settles
        cap.read()
    return cap


def wait(seconds):
    """Sleep that Pause or Close can interrupt. Returns False if interrupted."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event.is_set() or pause_event.is_set():
            return False
        time.sleep(0.1)
    return True


def calibrate(cap, landmarker):
    set_status("Sit straight...")
    if not wait(2):
        return None
    set_status("Calibrating...")

    samples = []
    attempts = 0
    while (len(samples) < CALIBRATION_SAMPLES and attempts < 60
           and not stop_event.is_set() and not pause_event.is_set()):
        m = read_pose(cap, landmarker)
        attempts += 1
        if m is not None:
            samples.append(m)
        time.sleep(0.1)

    if len(samples) < CALIBRATION_SAMPLES // 2:
        return None
    base = summarize(samples)
    if base["ratio"] < 0.05:      # head not clearly above shoulders: bad calibration
        return None
    return base


def Detector():
    if not os.path.exists(MODEL_PATH):
        notify("Posture Detector", "Model file missing.")
        set_status("Model missing")
        return

    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.IMAGE,
        num_poses=1,
    )

    cap = None
    history = collections.deque(maxlen=BUFFER_SIZE)

    try:
        with PoseLandmarker.create_from_options(options) as landmarker:
            baseline = None
            slouch_start = None
            last_notify = 0
            calib_notified = False
            fail_notified = False

            while not stop_event.is_set():

                # ---- PAUSED: release camera so its light turns OFF ----
                if pause_event.is_set():
                    if cap is not None:
                        cap.release()
                        cap = None
                    set_status("Paused")
                    slouch_start = None
                    history.clear()
                    time.sleep(0.3)
                    continue

                # ---- START / RESUME: open the camera ----
                if cap is None:
                    set_status("Opening camera...")
                    cap = open_camera()
                    if cap is None:
                        notify("Posture Detector", "Could not access the camera.")
                        set_status("Camera busy - press Resume")
                        pause_event.set()
                        continue
                    set_status("Monitoring" if baseline else "Starting...")

                # ---- CALIBRATION ----
                if baseline is None or recalibrate_event.is_set():
                    recalibrate_event.clear()
                    if not calib_notified:
                        notify("Posture Detector", "Sit straight, calibrating posture...")
                        calib_notified = True
                    new = calibrate(cap, landmarker)
                    if new is not None:
                        baseline = new
                        slouch_start = None
                        history.clear()
                        calib_notified = False
                        fail_notified = False
                        set_status("Monitoring")
                        notify("Posture Detector", "Calibrated successfully.")
                    elif pause_event.is_set() or stop_event.is_set():
                        pass
                    else:
                        set_status("Can't see you...")
                        if not fail_notified:
                            notify("Posture Detector",
                                   "Couldn't see your head and shoulders. Retrying...")
                            fail_notified = True
                        time.sleep(2)
                    continue

                # ---- NORMAL MONITORING ----
                m = read_pose(cap, landmarker)
                if m is None:
                    history.clear()
                    slouch_start = None
                    set_status("Can't see head/shoulders")
                else:
                    history.append(m)
                    cur = summarize(history)
                    drop, lean, head = slouch_signals(cur, baseline)
                    slouching = (drop > SLOUCH_DROP or lean > LEAN_GROW or head > HEAD_DOWN)

                    if slouching:
                        now = time.time()
                        if slouch_start is None:
                            slouch_start = now
                        elif (now - slouch_start >= SLOUCH_SECONDS
                              and now - last_notify > NOTIFY_COOLDOWN):
                            notify("Posture Alert!", "You're slouching. Sit up straight!")
                            last_notify = now
                    else:
                        slouch_start = None

                    if SHOW_NUMBERS:
                        set_status(f"drop {drop * 100:.0f} lean {lean * 100:.0f} "
                                   f"head {head * 100:.0f}")
                    else:
                        set_status("Monitoring")

                time.sleep(CHECK_INTERVAL)
    finally:
        if cap is not None:
            cap.release()


# ---------------- Tray & UI ----------------
def make_icon():
    img = Image.new("RGB", (64, 64), (30, 120, 200))
    d = ImageDraw.Draw(img)
    d.ellipse((22, 8, 42, 28), fill="white")
    d.rectangle((14, 34, 50, 56), fill="white")
    return img


def build_tray():
    menu = pystray.Menu(
        pystray.MenuItem("Show control box", lambda i, it: ui_queue.put("show"), default=True),
        pystray.MenuItem(lambda item: "Resume" if pause_event.is_set() else "Pause",
                         lambda i, it: ui_queue.put("toggle_pause")),
        pystray.MenuItem("Recalibrate", lambda i, it: recalibrate_event.set()),
        pystray.MenuItem("Test alert",
                         lambda i, it: notify("Posture Alert!", "This is a test alert.")),
        pystray.MenuItem("Quit", lambda i, it: ui_queue.put("quit")),
    )
    return pystray.Icon("Posture Detector", make_icon(), "Posture Detector", menu)


class ControlBox:
    BG = "#1f2937"
    FG = "#e5e7eb"

    def __init__(self, tray, worker):
        self.tray = tray
        self.worker = worker
        self.root = tk.Tk()
        self.root.title("Posture Detector")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=self.BG)

        w, h = 190, 54
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 70}")

        self.status_lbl = tk.Label(self.root, text="Starting...", bg=self.BG,
                                   fg=self.FG, font=("Segoe UI", 8))
        self.status_lbl.pack(fill="x", pady=(4, 0))

        row = tk.Frame(self.root, bg=self.BG)
        row.pack(pady=(2, 4))

        self.hide_btn = self._button(row, "Hide", self.hide)
        self.pause_btn = self._button(row, "Pause", self.toggle_pause)
        self.close_btn = self._button(row, "Close", self.close, bg="#b91c1c")

        for widget in (self.root, self.status_lbl, row):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(300, self.refresh)

    def _button(self, parent, text, cmd, bg="#374151"):
        b = tk.Button(parent, text=text, command=cmd, width=5, bg=bg, fg="white",
                      activebackground="#4b5563", activeforeground="white",
                      relief="flat", font=("Segoe UI", 8), bd=0, padx=2, pady=2)
        b.pack(side="left", padx=3)
        return b

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def hide(self):
        self.root.withdraw()
        notify("Posture Detector",
               "Still running (camera on). Open Posture Detector again, or use the tray icon, to bring the box back.")

    def show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def toggle_pause(self):
        if pause_event.is_set():
            pause_event.clear()
        else:
            pause_event.set()

    def close(self):
        stop_event.set()
        try:
            self.tray.stop()
        except Exception:
            pass
        self.worker.join(timeout=3)      # lets the detector release the camera
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def refresh(self):
        try:
            while True:
                cmd = ui_queue.get_nowait()
                if cmd == "show":
                    self.show()
                elif cmd == "toggle_pause":
                    self.toggle_pause()
                elif cmd == "quit":
                    self.close()
                    return
        except queue.Empty:
            pass
        self.status_lbl.config(text=status["text"])
        self.pause_btn.config(text="Resume" if pause_event.is_set() else "Pause")
        self.root.after(300, self.refresh)

    def run(self):
        self.root.mainloop()


def main():
    threading.Thread(target=_instance_server, daemon=True).start()

    worker = threading.Thread(target=Detector, daemon=True)
    worker.start()

    tray = build_tray()
    tray_ref["icon"] = tray #type:ignore
    tray.run_detached()

    ControlBox(tray, worker).run()


if __name__ == "__main__":
    main()