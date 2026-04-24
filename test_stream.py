import cv2
import yt_dlp

url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
ydl_opts = {
    'format': 'best[protocol^=https]',
    'quiet': True,
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=False)
    stream_url = info['url']
    print("Stream URL:", stream_url[:100], "...")

cap = cv2.VideoCapture(stream_url)
if not cap.isOpened():
    print("Cannot open stream")
else:
    ret, frame = cap.read()
    print("Frame read success:", ret)
    cap.release()
