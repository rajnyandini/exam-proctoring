
import cv2
import time

camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

if not camera.isOpened():
    print("Camera could not be opened.")
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

