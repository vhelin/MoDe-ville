################################################################################
#                                                                              #
#  (Mo)tion (De)tect                                                           #
#  Detects Motion in a YouTube streams or video files                          #
#                                                                              #
#  Usage:                                                                      #
#    $ ./python MoDe.py -s https://www.youtube.com/watch?v=<ID>                #
#    $ ./python MoDe.py -s file.mp4                                            #
#                                                                              #
#  Notes:                                                                      #
#    Sensitivity is VERY HIGH.                                                 #
#    increase -G, --gaussian-blur to something higher like 25 (Default 15)     #
#    increase -C, --contourarea to something HUGE like 10000 (Default 201)     #
#                                                                              #
#    Hitting "r" while in screen will reset all values to normal defaults      #
#      G - 25 , D - 5, C - 10000                                               #
#                                                                              #                                                                              #
#  Dependencies:                                                               #
#    pip install pafy                                                          #
#    pip install youtube-dl                                                    #
#    pip install opencv-python                                                 #
#                                                                              #
#    backend-youtube-dl will need to be modified to disable likes              #
#                                                                              #
################################################################################

from modules.video_stream import VideoStream
from modules.key_clip_writer import KeyClipWriter
from modules.draw_contours import draw
import modules.osd as osd
import argparse
import cv2
import datetime
import os
import pafy
import time
import numpy

ap = argparse.ArgumentParser()
#ap.add_argument("-h", "--help", help="This message")
ap.add_argument("-c", "--codec", type=str, default='avc1', help="avc1 x264 mpv4 divx")
ap.add_argument("-u", "--cuda", type=int, default=None, help="Use CUDA instead of CPU")
ap.add_argument("-q", "--quad", type=int, default=None, help="Enable Quadrant Splitting")
ap.add_argument("-s", "--source", help="http YouTube URL or File Path")
ap.add_argument("-t", "--threading", type=int, default=None, help="Enable Threading")
ap.add_argument("-v", "--verbose", type=int, default=None, help="Enable Verbose")
ap.add_argument("-C", "--contourarea", type=int, default=201, help="Define contourArea")
ap.add_argument("-D", "--delta", type=int, default=25, help="Define Sensitivity Delta")
ap.add_argument("-g", "--gaussianblur", type=int, default=11, help="Define gaussianBlur value")
ap.add_argument("-o", "--outdir", type=str, default="./saved", help="Directory to save clips/captures")
ap.add_argument("-m", "--mode", type=int, default=None, help="Enable Motion Detection")
ap.add_argument("-d", "--debug", type=int, default=None, help="Show Debug Video Frames")
args = vars(ap.parse_args())

if args.get('verbose', None) is None:
    verbose = False
else:
    verbose = True
if args.get('threading', None) is None:
    use_threading = False
else:
    use_threading = True 
if args.get('quad', None) is None:
    show_quadrants = False 
else:
    show_quadrants = True 
if args.get('mode', None) is None:
    motion_detect = False
else:
    motion_detect = True
if args.get('debug', None) is None:
    debug_show = False
else:
    debug_show = True
if args.get('cuda', None) is None:
    use_cuda = False
else:
    use_cuda = True

# Set codec variable from CLI Option/Defaults
codec = args["codec"]

if verbose: print("(Mo)tion (De)tect Started...")

buffer_size = 684

kcw = KeyClipWriter(bufSize = buffer_size)
consecFrames = 0

if use_cuda:
    print("CUDA Device Count = " + str(cv2.cuda.getCudaEnabledDeviceCount()))
    print(cv2.getBuildInformation())
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]="video_codec;h264_cuvid"
    
out_dir = args["outdir"]

# Sensitivity Settings
gnum = args["gaussianblur"]
cnum = args["contourarea"]
dnum = args["delta"]

# Initialize count and show_status
count = 0
show_status = 1

# Stream or Local File
if 'http' in args["source"]:
    url = args["source"]
    video = pafy.new(url)
    if verbose:
        for stream in video.streams:
            print(stream)
    v_title = video.title
    best = video.getbest(preftype="mp4")
    if verbose: print("Selected:", best)
    path = best.url
else:
    path = args["source"] 
    v_title = os.path.basename(path)

# Baseline and setting status_list
baseline_image = None
status_list = [None,None]

if use_threading:
    vs = VideoStream(path).start()
    time.sleep(5) # Get a chance to buffer some frames
else:
    if use_cuda:
        video = cv2.cudacodec.createVideoReader(path)
        # keep the video data in YUV
        #video.set(cv2.CAP_PROP_CONVERT_RGB, 0.0)
        #video.set(cv2.cudacodec.ColorFormat_BGR)
        #video.set(cv2.cudacodec.ColorFormat_YUV)
    else:
        #video = cv2.VideoCapture(path, cv2.CAP_FFMPEG, [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY ])
        video = cv2.VideoCapture(path)
    
if verbose:
    print("Video Capture Started")

if use_cuda:
    # gaussian filter
    filter = cv2.cuda.createGaussianFilter(srcType=cv2.CV_8UC1, dstType=cv2.CV_8UC1, ksize=(gnum, gnum), sigma1=0, sigma2=0)
    # GPU material
    cuda_gpumat = cv2.cuda_GpuMat()

def iteration_cuda() -> int:
    global gnum
    global baseline_image
    global dnum
    global motion_detect
    global cnum
    global consecFrames
    global count
    global show_status
    global filter
    global cuda_gpumat
    global gray_frame
    
    while True:
        if use_threading:
            frame = vs.read()
        else:
            check, frame_gpu = video.nextFrame()
            #format_info = video.format()
            #print(format_info.chromaFormat) # 1 here is YUV420 - https://docs.opencv.org/3.4/d0/d61/group__cudacodec.html
            #print(f'frame resolution: {frame_gpu.size()}')
            #print(f'frame color space type: {frame_gpu.type()}')
            
        if frame_gpu is None:
            print("Unable to get frame")
            quit()

        #if baseline_image is None:
        #    # create gray_frame
        #    gray_frame = cv2.cuda.cvtColor(frame_gpu, cv2.COLOR_YUV2BGR)
        #    gray_frame = cv2.cuda.cvtColor(gray_frame, cv2.COLOR_BGR2GRAY)

        frame = frame_gpu.download()
        (frameHeight, frameWidth) = frame.shape[:2]
        (frameHalfHeight, frameHalfWidth) = (frameHeight // 2, frameWidth // 2)
        
        #frame_gpu.convertTo(cv2.CV_32FC1, gray_frame)
        
        #gray_frame = frame_gpu.reshape(1)
        gray_frame = cv2.cuda.cvtColor(frame_gpu, cv2.COLOR_YUV2BGR)
        gray_frame = cv2.cuda.cvtColor(gray_frame, cv2.COLOR_BGR2GRAY)
        #gray_frame = cv2.cuda.cvtColor(frame_gpu, cv2.COLOR_YUV2GRAY_YV12) # cv2.COLOR_BGR2GRAY) # COLOR_YUV2GRAY_UYVY) - https://www.ccoderun.ca/programming/doxygen/opencv/group__imgproc__color__conversions.html#gga4e0972be5de079fed4e3a10e24ef5ef0ac04bb1de2f067221ccf4659c8a4be4ea
        gray_frame = cv2.cuda_Filter.apply(filter, gray_frame)
        
        status = 0
        #gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        #gray_frame = cv2.GaussianBlur(gray_frame, (gnum, gnum), 0)
        updateConsecFrames = True

        if baseline_image is None:
            baseline_image = gray_frame
        else:
            break

    delta = cv2.cuda.absdiff(baseline_image, gray_frame)
    threshold = cv2.cuda.threshold(delta, dnum, 255, cv2.THRESH_BINARY)[1]
    threshold = threshold.download()
    (contours, _) = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    #delta = cv2.absdiff(baseline_image, gray_frame)
    #threshold = cv2.threshold(delta, dnum, 255, cv2.THRESH_BINARY)[1]
    #(contours, _) = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if motion_detect:
        for contour in contours:
            draw(frame, contour, cnum)
            status=1
    else:
        show_status=0
        status=1
    
    status_list.append(status)

    if show_status == 1:
        osd.display_status(frame, gnum, cnum, dnum)

    if debug_show:
        delta = delta.download()
        gray_frame = src.download()
        cv2.imshow("gray_frame Frame", gray_frame)
        cv2.imshow("Delta Frame", delta)
        cv2.imshow("Threshold Frame", threshold)

    if show_quadrants:
        cv2.imshow(v_title + " Q1",frame[0:frameHalfHeight, 0:frameHalfWidth])
        cv2.imshow(v_title + " Q2",frame[0:frameHalfHeight, frameHalfWidth:frameWidth])
        cv2.imshow(v_title + " Q3",frame[frameHalfHeight:frameHeight, 0:frameHalfWidth])
        cv2.imshow(v_title + " Q4",frame[frameHalfHeight:frameHeight, frameHalfWidth:frameWidth])
    else:
        cv2.imshow(v_title, frame)

    # Key input jive
    key = cv2.pollKey()
    if key == ord('Q'):
        if status == 1:
            return 0
    if key == ord('h'): 
        if status == 1 and show_status == 0:
            show_status = 1
        else:
            show_status = 0
    if key == ord('m'): 
        if status == 1 and motion_detect:
            motion_detect = False
        else:
            motion_detect = True
    if key == ord('G'):
        if status == 1:
            gnum = (gnum + 2)
            # recreate the gaussian filter
            filter = cv2.cuda.createGaussianFilter(srcType=cv2.CV_8UC1, dstType=cv2.CV_8UC1, ksize=(gnum, gnum), sigma1=0, sigma2=0)
    if key == ord('g'):
        if status == 1:
            if gnum == 1:
                gnum = 1
            else:
                gnum = (gnum - 2)
            # recreate the gaussian filter
            filter = cv2.cuda.createGaussianFilter(srcType=cv2.CV_8UC1, dstType=cv2.CV_8UC1, ksize=(gnum, gnum), sigma1=0, sigma2=0)
    if key == ord('C'):
        if status == 1:
            cnum = (cnum + 1)
    if key == ord('c'):
        if status == 1:
            if cnum == 1:
                cnum = 1
            else:
                cnum = (cnum - 1)
    if key == ord('>'):
        if status == 1:
            cnum = (cnum + 200)
    if key == ord('<'):
        if status == 1:
            if cnum < 201:
                cnum = 1
            else:
                cnum = (cnum - 200)
    if key == ord('D'):
        if status == 1:
            dnum = (dnum + 1)
    if key == ord('d'):
        if status == 1:
            if dnum == 1:
                dnum = 1
            else:
                dnum = (dnum - 1)
    if key == ord('r'):
        if status == 1:
            # Reset settings
            gnum = 21
            cnum = 500 
            dnum = 25
    if key == ord('s'):
        timestamp = datetime.datetime.now()
        img_name = "{}/{}.png".format(out_dir, 
                   timestamp.strftime("%Y%m%d-%H%M%S"))
        cv2.imwrite(img_name, frame)
        count += 1
    if key == ord('S'):
        if not kcw.recording:
            timestamp = datetime.datetime.now()
            p = "{}/{}.mp4".format(out_dir,
                timestamp.strftime("%Y%m%d-%H%M%S"))
            print("Recording...")
            kcw.start(p, cv2.VideoWriter_fourcc(*codec), 20, frameWidth, frameHeight)
    if updateConsecFrames:
        consecFrames += 1
    # update the key frame clip buffer
    kcw.update(frame)
    # if we are recording and reached a threshold on consecutive
    # number of frames with no action, stop recording the clip
    if kcw.recording and consecFrames == buffer_size:
        kcw.finish()
    # Stop Recording by pressing 'x'
    if key == ord('x'):
        if kcw.recording:
            kcw.finish()
    # Pause with 'p'
    if key == ord('p'):
        cv2.waitKey(-1)

    if use_threading:
        time.sleep(0.1)

    return 1

def iteration_cpu() -> int:
    global gnum
    global baseline_image
    global dnum
    global motion_detect
    global cnum
    global consecFrames
    global count
    global show_status
    
    while True:
        if use_threading:
            frame = vs.read()
        else:
            check, frame = video.read()

        if frame is None:
            print("Unable to get frame")
            quit()

        (frameHeight, frameWidth) = frame.shape[:2]
        (frameHalfHeight, frameHalfWidth) = (frameHeight // 2, frameWidth // 2)

        status = 0
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_frame = cv2.GaussianBlur(gray_frame, (gnum, gnum), 0)
        updateConsecFrames = True

        if baseline_image is None:
            baseline_image = gray_frame
        else:
            break

    delta = cv2.absdiff(baseline_image, gray_frame)
    threshold = cv2.threshold(delta, dnum, 255, cv2.THRESH_BINARY)[1]
    (contours, _) = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if motion_detect:
        for contour in contours:
            draw(frame, contour, cnum)
            status=1
    else:
        show_status=0
        status=1
    
    status_list.append(status)

    if show_status == 1:
        osd.display_status(frame, gnum, cnum, dnum)

    if debug_show:
        cv2.imshow("gray_frame Frame", gray_frame)
        cv2.imshow("Delta Frame", delta)
        cv2.imshow("Threshold Frame", threshold)

    if show_quadrants:
        cv2.imshow(v_title + " Q1",frame[0:frameHalfHeight, 0:frameHalfWidth])
        cv2.imshow(v_title + " Q2",frame[0:frameHalfHeight, frameHalfWidth:frameWidth])
        cv2.imshow(v_title + " Q3",frame[frameHalfHeight:frameHeight, 0:frameHalfWidth])
        cv2.imshow(v_title + " Q4",frame[frameHalfHeight:frameHeight, frameHalfWidth:frameWidth])
    else:
        cv2.imshow(v_title, frame)

    # Key input jive
    key = cv2.pollKey()
    if key == ord('Q'):
        if status == 1:
            return 0
    if key == ord('h'): 
        if status == 1 and show_status == 0:
            show_status = 1
        else:
            show_status = 0
    if key == ord('m'): 
        if status == 1 and motion_detect:
            motion_detect = False
        else:
            motion_detect = True
    if key == ord('G'):
        if status == 1:
            gnum = (gnum + 2)
    if key == ord('g'):
        if status == 1:
            if gnum == 1:
                gnum = 1
            else:
                gnum = (gnum - 2)
    if key == ord('C'):
        if status == 1:
            cnum = (cnum + 1)
    if key == ord('c'):
        if status == 1:
            if cnum == 1:
                cnum = 1
            else:
                cnum = (cnum - 1)
    if key == ord('>'):
        if status == 1:
            cnum = (cnum + 200)
    if key == ord('<'):
        if status == 1:
            if cnum < 201:
                cnum = 1
            else:
                cnum = (cnum - 200)
    if key == ord('D'):
        if status == 1:
            dnum = (dnum + 1)
    if key == ord('d'):
        if status == 1:
            if dnum == 1:
                dnum = 1
            else:
                dnum = (dnum - 1)
    if key == ord('r'):
        if status == 1:
            # Reset settings
            gnum = 21
            cnum = 500 
            dnum = 25
    if key == ord('s'):
        timestamp = datetime.datetime.now()
        img_name = "{}/{}.png".format(out_dir, 
                   timestamp.strftime("%Y%m%d-%H%M%S"))
        cv2.imwrite(img_name, frame)
        count += 1
    if key == ord('S'):
        if not kcw.recording:
            timestamp = datetime.datetime.now()
            p = "{}/{}.mp4".format(out_dir,
                timestamp.strftime("%Y%m%d-%H%M%S"))
            print("Recording...")
            kcw.start(p, cv2.VideoWriter_fourcc(*codec), 20, frameWidth, frameHeight)
    if updateConsecFrames:
        consecFrames += 1
    # update the key frame clip buffer
    kcw.update(frame)
    # if we are recording and reached a threshold on consecutive
    # number of frames with no action, stop recording the clip
    if kcw.recording and consecFrames == buffer_size:
        kcw.finish()
    # Stop Recording by pressing 'x'
    if key == ord('x'):
        if kcw.recording:
            kcw.finish()
    # Pause with 'p'
    if key == ord('p'):
        cv2.waitKey(-1)

    if use_threading:
        time.sleep(0.1)

    return 1

# while vs.more():
while True:
    if use_cuda:
        tic = time.perf_counter()
        r = iteration_cuda()
        toc = time.perf_counter()
        print(f"iteration_cuda(): time {toc - tic:0.5f} seconds")
    else:
        tic = time.perf_counter()
        r = iteration_cpu()
        toc = time.perf_counter()
        print(f"iteration_cpu(): time {toc - tic:0.5f} seconds")
    if r == 0:
        break

if kcw.recording:
    kcw.finish()
#Clean up, Free memory
if use_threading:
    vs.stop()
cv2.destroyAllWindows
