
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
print(f"Connecting to {label} (Index {cam_index})...")
camera = cv2.VideoCapture(cam_index, cv2.CAP_AVFOUNDATION)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
camera.set(cv2.CAP_PROP_FPS, 15)

if not camera.isOpened():
    print(f"Could not open webcam on index {cam_index}.")
    raise SystemExit(1)

cascade_path = (
    cv2.data.haarcascades
    + "haarcascade_frontalface_default.xml"
)
face_detector = cv2.CascadeClassifier(cascade_path)

if face_detector.empty():
    print("Could not load face detector.")
    camera.release()
    raise SystemExit(1)

print("Face detection started. Press q to quit.")

try:
    while True:
        success, frame = camera.read()

        if not success:
            print("Could not read webcam frame.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        faces = face_detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(50, 50)
        )

        face_count = len(faces)

        for (x, y, w, h) in faces:
            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )

        status = (
            "NO FACE DETECTED"
            if face_count == 0
            else "MULTIPLE FACES"
            if face_count >= 2
            else "ONE FACE DETECTED"
        )

        color = (0, 0, 255) if face_count != 1 else (0, 255, 0)

        cv2.putText(
            frame,
            f"Faces: {face_count} | {status}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2
        )

        cv2.imshow("Exam Proctoring - Face Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    camera.release()
    cv2.destroyAllWindows()

