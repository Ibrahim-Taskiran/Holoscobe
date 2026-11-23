"""Holoscobe hand gesture control."""
import os

# Must be set before cv2 loads: with hardware transforms OpenCV's MSMF backend needs ~11 s to open the
# camera (measured 11.4 s vs 0.6 s without), so the first seconds of every start had no hands and no strings.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

__version__ = "1.1.0"
