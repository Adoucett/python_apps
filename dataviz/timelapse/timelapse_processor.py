# timelapse_processor.py
"""
Processing module for Satellite Timelapse Generator.
Contains all non-GUI logic: metadata loading, quality scoring, outlier detection,
image enhancement, alignment, overlay, and timelapse creation.
"""
import os
import cv2
import json
import time
import numpy as np
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Tuple, Optional
from statistics import mean, stdev
from PIL import Image, ImageDraw, ImageFont

# Video codecs for timelapse creation
VIDEO_CODECS = {
    "mp4": {"fourcc": "mp4v", "extension": ".mp4"},
    "avi": {"fourcc": "XVID", "extension": ".avi"}
}

# Configure logging
logging.basicConfig(filename="timelapse_log.txt", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Utility functions
def test_codec(codec: str) -> bool:
    """Test if a video codec is supported."""
    try:
        fourcc = cv2.VideoWriter_fourcc(*VIDEO_CODECS[codec]["fourcc"])
        temp = cv2.VideoWriter("test.mp4", fourcc, 30, (640, 480))
        temp.release()
        os.remove("test.mp4")
        return True
    except Exception:
        return False


def load_metadata(file_path: str) -> Optional[Dict]:
    """Load and return metadata properties from JSON."""
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        return data.get("properties", {})
    except Exception as e:
        logging.warning(f"Failed to load metadata {file_path}: {e}")
        return None


def compute_quality_score(metadata: Dict) -> float:
    """Compute quality score based on metadata weights."""
    weights = {
        "cloud_percent": -0.2,
        "heavy_haze_percent": -0.3,
        "light_haze_percent": -0.1,
        "shadow_percent": -0.15,
        "snow_ice_percent": -0.2,
        "anomalous_pixels": -0.5,
        "clear_confidence_percent": 0.1,
        "visible_confidence_percent": 0.05,
        "view_angle": -0.05
    }
    score = 100.0
    for key, w in weights.items():
        score += metadata.get(key, 0) * w
    if metadata.get("quality_category", "standard") != "standard":
        score -= 20.0
    if not metadata.get("ground_control", True):
        score -= 10.0
    return max(0.0, min(100.0, score))


def detect_outliers(scores: List[float], threshold: float = 1.5) -> List[bool]:
    """Mark scores as outliers if deviating beyond threshold*std."""
    if len(scores) < 2:
        return [False] * len(scores)
    avg = mean(scores)
    std = stdev(scores)
    return [abs(s - avg) > threshold * std for s in scores]

# Image enhancement & alignment

def white_balance(img: np.ndarray) -> np.ndarray:
    """Gray-world white balance."""
    b, g, r = cv2.split(img)
    avg = (np.mean(b) + np.mean(g) + np.mean(r)) / 3
    return cv2.merge([np.clip(b * (avg / np.mean(b)), 0,255).astype(np.uint8),
                       np.clip(g * (avg / np.mean(g)), 0,255).astype(np.uint8),
                       np.clip(r * (avg / np.mean(r)), 0,255).astype(np.uint8)])


def align_frames(img: np.ndarray, ref: np.ndarray,
                 method: str = "ecc") -> np.ndarray:
    """Align img to ref via ECC or ORB fallback."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    if gray.shape != ref_gray.shape:
        img = cv2.resize(img, (ref_gray.shape[1], ref_gray.shape[0]))
    if method == "ecc":
        try:
            warp_mat = np.eye(2,3, dtype=np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,100,1e-4)
            _, wm = cv2.findTransformECC(ref_gray, gray, warp_mat, cv2.MOTION_EUCLIDEAN, criteria)
            h,w = ref.shape[:2]
            return cv2.warpAffine(img, wm, (w,h), flags=cv2.INTER_LINEAR+cv2.WARP_INVERSE_MAP)
        except:
            logging.warning("ECC failed, using feature fallback")
    # ORB fallback
    orb = cv2.ORB_create()
    kp1, des1 = orb.detectAndCompute(ref_gray, None)
    kp2, des2 = orb.detectAndCompute(gray, None)
    if des1 is None or des2 is None:
        return img
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(des1,des2)
    matches = sorted(matches, key=lambda x: x.distance)[:50]
    if len(matches)<4:
        return img
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1,1,2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1,1,2)
    M,_ = cv2.findHomography(dst, src, cv2.RANSAC,5.0)
    if M is None:
        return img
    h,w = ref.shape[:2]
    return cv2.warpPerspective(img, M, (w,h))


def match_histograms(img: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """CLAHE-based histogram match on L channel."""
    if img.shape[:2]!=ref.shape[:2]:
        img = cv2.resize(img,(ref.shape[1], ref.shape[0]))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    rl, a, b = cv2.split(cv2.cvtColor(ref, cv2.COLOR_BGR2LAB))
    l,_,_ = cv2.split(lab)
    cl = cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(l)
    return cv2.cvtColor(cv2.merge([cl,a,b]), cv2.COLOR_LAB2BGR)


def enhance_contrast(img: np.ndarray) -> np.ndarray:
    """CLAHE on image lightness."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l,a,b = cv2.split(lab)
    cl = cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(l)
    return cv2.cvtColor(cv2.merge([cl,a,b]), cv2.COLOR_LAB2BGR)


def add_metadata_overlay(img: np.ndarray, text: str,
                         pos: str="bottom", size:int=24) -> np.ndarray:
    """Draw text overlay with background."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        font = ImageFont.load_default()
    w,h = draw.textsize(text, font=font)
    x=10; y = pil.height-h-10 if pos=="bottom" else 10
    draw.rectangle([x-5,y-5,x+w+5,y+h+5], fill=(0,0,0,128))
    draw.text((x,y), text, font=font, fill=(255,255,255))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def process_frame(args: Tuple[str,int,Dict,Optional[np.ndarray]] ) -> Dict:
    """Process TIFF => RGB => optional enhancements => overlay."""
    path,i,params,ref = args
    try:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return {"status":"error","message":"read failed"}
        if img.dtype!=np.uint8:
            img = cv2.normalize(img,None,0,255,cv2.NORM_MINMAX).astype(np.uint8)
        if len(img.shape)==2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2]==4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        if params.get("white_balance"): img=white_balance(img)
        if params.get("stabilize") and ref is not None and i>0:
            img=align_frames(img,ref)
        if params.get("histogram_matching") and ref is not None:
            img=match_histograms(img,ref)
        if params.get("contrast_enhance"): img=enhance_contrast(img)
        out_size = params.get("output_size")
        if out_size and out_size!="original":
            img = cv2.resize(img, out_size, interpolation=cv2.INTER_LANCZOS4)
        if params.get("metadata_overlay"):
            # filename prefix used as date
            date_str = os.path.basename(path).split("_")[0]
            img = add_metadata_overlay(img, date_str,
                                       params.get("overlay_position","bottom"),
                                       params.get("font_size",24))
        return {"status":"ok","frame":img,"original_size":img.shape[1::-1]}
    except Exception as e:
        logging.error(f"Frame proc failed {path}: {e}")
        return {"status":"error","message":str(e)}


def create_timelapse(input_dir:str, output_file:str, params:Dict, batch_size:int=100) -> Dict:
    """Run through filtered files, write to video."""
    os.makedirs(os.path.dirname(output_file),exist_ok=True)
    files = params.get("filtered_files",[])
    if not files:
        raise ValueError("no TIFFs")
    # reference
    ref_out = process_frame((files[0],0,params,None))
    if ref_out["status"]!="ok":
        raise ValueError("ref frame fail: "+ref_out["message"])
    ref_img = ref_out["frame"]
    orig = ref_out["original_size"]
    size = params.get("output_size") or orig
    if size=="original": size=orig
    codec=params.get("codec","mp4")
    if not test_codec(codec): codec="mp4"
    fourcc = cv2.VideoWriter_fourcc(*VIDEO_CODECS[codec]["fourcc"])
    writer = cv2.VideoWriter(output_file,fourcc,params.get("fps",30),size)
    writer.write(ref_img)
    stats={"processed_frames":1,"errors":0}
    jobs=[(f,i+1,params,ref_img) for i,f in enumerate(files[1:])]
    start=time.time()
    for i in range(0,len(jobs),batch_size):
        batch=jobs[i:i+batch_size]
        with ProcessPoolExecutor(max_workers=params.get("max_workers",os.cpu_count())) as ex:
            for res in ex.map(process_frame,batch):
                if res["status"]=="ok":
                    writer.write(res["frame"])
                    stats["processed_frames"]+=1
                else:
                    stats["errors"]+=1
    writer.release()
    stats["time"]=time.time()-start
    logging.info(f"Timelapse stats: {stats}")
    return stats
