# Posture Detector

A small Windows desktop app that uses a webcam to notice sustained changes in sitting posture and provide a gentle reminder. It runs in the system tray, so posture monitoring does not require keeping a large window open.

Access App: https://posturedetector.vercel.app?_vercel_share=YTKpTHChUjZuK9vUKnwBqduRscHW2HGl

## Project overview

Long periods of sitting with a forward lean or lowered head can contribute to discomfort and poor posture habits. Posture Detector is designed to make users more aware of those habits by giving a reminder when it detects a sustained change from their own calibrated sitting position.

The app is a self-awareness tool, not a medical device. It does not diagnose, treat, or prevent a health condition.

## How it works

1. The app opens the webcam and asks the user to sit comfortably upright.
2. MediaPipe detects the nose and shoulders, and the app records a short personal baseline.
3. OpenCV supplies low-resolution webcam frames for pose analysis.
4. The app compares the current nose-to-shoulder relationship, apparent shoulder width, and nose position with the baseline.
5. A reminder appears when one of the posture signals remains beyond its threshold for several seconds.

A rolling median of recent readings helps reduce the effect of brief, noisy changes. The user can recalibrate at any time.

## Features

- Live posture monitoring with a compact, movable control box.
- System-tray controls to pause, resume, recalibrate, test an alert, or quit.
- Camera release while paused.
- Windows desktop notifications, with a tray notification fallback.
- Single-instance behavior: opening the app again brings the existing control box back.

## Technology

- **Python** — application logic and background monitoring.
- **MediaPipe Pose Landmarker** — detects pose landmarks from each frame.
- **OpenCV** — captures webcam frames and converts them to the color format used for analysis.
- **Tkinter** — compact control interface.
- **pystray** — system-tray icon and menu.
- **Plyer** — desktop notifications.
- **Pillow** — creates the tray icon image.

## Performance

The app requests **320 × 240** camera frames and checks posture about **three times per second**. It tracks one pose and uses a small five-reading median buffer. These choices are intended to keep routine processing modest compared with analyzing full-resolution video continuously.

Actual CPU use and responsiveness depend on the webcam, computer, and installed dependencies; performance has not been benchmarked across devices. Pause monitoring when it is not needed—the app releases the camera while paused.

## Privacy

Pose analysis is performed locally using the webcam and the bundled MediaPipe model. The application code does not upload webcam frames to a server. The webcam is active while monitoring and released while paused or when the app exits.

## Run from source

Use Windows PowerShell from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
Copy-Item .\pose_landmarker_lite.task .\website\pose_landmarker_lite.task
python .\website\Posture_Detection.py
```

The model file, `pose_landmarker_lite.task`, must be beside `Posture_Detection.py` when running from source. The copy command above places the repository's model beside the script.

If PowerShell blocks virtual-environment activation, use the environment's Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe .\website\Posture_Detection.py
```

## Using the app

Sit in view of the webcam and follow the initial calibration prompt. Use the control box or tray menu to pause/resume monitoring or recalibrate after changing your seating or camera position. Good lighting and a clear view of the head and shoulders help pose detection.

## Limitations

- Detection depends on webcam framing, lighting, and visibility of the head and shoulders.
- Alerts are reminders, not a substitute for professional medical advice.
