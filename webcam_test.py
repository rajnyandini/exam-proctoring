
import sys
import cv2
import time

cam_index = 0
if len(sys.argv) > 1:
    try:
        cam_index = int(sys.argv[1])
    except ValueError:
        cam_index = 0

label = "Native Laptop Camera" if cam_index == 0 else f"External USB Camera (Index {cam_index})"
print(f"Testing {label} (Index {cam_index}) using AVFoundation...")
camera = cv2.VideoCapture(cam_index, cv2.CAP_AVFOUNDATION)

if not camera.isOpened():
    print(f"Camera index {cam_index} could not be opened.")
    raise SystemExit(1)

# Request a lighter stream for smoother video
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
camera.set(cv2.CAP_PROP_FPS, 15)

print("Camera started. Press q to quit.")

while True:
    success, frame = camera.read()

    if not success:
        print("Frame read failed. Retrying...")
        time.sleep(0.1)
        continue

    cv2.imshow("Exam Proctoring - Webcam Test", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()

