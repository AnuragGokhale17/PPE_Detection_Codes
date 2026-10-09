import cv2
import os

# Extremely important: Set FFmpeg timeout so the script doesn't hang on bad URLs
# 3000 milliseconds = 3 seconds per path.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;3000"

IP = "10.0.65.150"
PORT = "554"
USER = "iiot"
PASS_ENCODED = "Toshiba%40123"

# Exhaustive list of all possible RTSP paths
PATHS_TO_TEST =[
    # 1. Modern Hanwha / Wisenet Native Paths (Profiles 1-4)
    "/profile1/media.smp",
    "/profile2/media.smp",
    "/profile3/media.smp",
    "/profile4/media.smp",
    
    # 2. Multi-Sensor / NVR Channel 1 (Sensor 0)
    "/0/profile1/media.smp",
    "/0/profile2/media.smp",
    "/0/profile3/media.smp",
    
    # 3. Multi-Sensor / NVR Channel 2 (Sensor 1)
    "/1/profile1/media.smp",
    "/1/profile2/media.smp",
    
    # 4. Wisenet NVR specific paths
    "/LiveChannel/0/media.smp",
    "/LiveChannel/1/media.smp",
    
    # 5. ONVIF Variations (Including your original request)
    "/onvif/profile1/media.smp",
    "/onvif/profile2/media.smp",
    "/onvif/media.smp",
    "/onvif1",
    "/onvif2",
    
    # 6. Legacy Samsung Techwin paths
    "/video1",
    "/video2",
    "/video3",
    "/profile1",
    "/profile2",
    "/h264",
    "/mjpeg",
    "/mpeg4",
    
    # 7. Common Generic / Alternative IP Camera Paths
    "/1/stream1",
    "/1/stream2",
    "/stream1",
    "/stream2",
    "/media/video1",
    "/media/video2",
    "/media/media.smp",
    "/live/0/h264.sdp",
    "/live/1/h264.sdp",
    "/ch01/0",
    "/ch01/1",
    
    # 8. Dahua / Hikvision / Axis Fallbacks (Sometimes useful if firmware is OEM)
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    "/Streaming/Channels/101",
    "/Streaming/Channels/102",
    "/axis-media/media.amp"
]

print(f"Starting Exhaustive RTSP Tester for {IP}:{PORT}...\n")
print(f"Testing {len(PATHS_TO_TEST)} different paths. This may take about {len(PATHS_TO_TEST) * 3} seconds.\n")

working_urls =[]

for path in PATHS_TO_TEST:
    url = f"rtsp://{USER}:{PASS_ENCODED}@{IP}:{PORT}{path}"
    print(f"Testing: {path:<35} ... ", end="", flush=True)
    
    try:
        # Attempt to open video stream
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        
        if cap.isOpened():
            # Try to read one frame to confirm video data is flowing
            ret, frame = cap.read()
            if ret:
                print("[SUCCESS] Video frame grabbed!")
                working_urls.append(url)
                
                # Show the successful frame for 1 second to prove it works
                cv2.imshow(f"Working: {path}", frame)
                cv2.waitKey(1000)
                cv2.destroyAllWindows()
            else:
                print("[CONNECTED BUT NO VIDEO] Stream opened, but no frames (Likely H.265 codec issue).")
            
            cap.release()
        else:
            print("[FAILED]")
    except Exception as e:
        print(f"[ERROR] {e}")

print("\n" + "="*50)
print("TESTING COMPLETE")
print("="*50)

if working_urls:
    print(f"Found {len(working_urls)} fully working URL(s):")
    for w_url in working_urls:
        print(f" -> {w_url}")
else:
    print("CRITICAL: NO WORKING URLS FOUND.")
    print("\nIf this tested 40+ paths and NONE worked, the path is NOT your issue.")
    print("Please check the following:")
    print("1. PASSWORD BUG: OpenCV often breaks when using '%40' in the password. Change the camera password to remove the '@' symbol and try again.")
    print("2. RTSP DISABLED: Log into the camera web UI -> Network -> Make sure RTSP is literally checked ON.")
    print("3. WRONG PORT: Port 554 might be blocked by a firewall, or the camera is configured to a different RTSP port.")