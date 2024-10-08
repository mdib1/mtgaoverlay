import cv2
import numpy as np
import win32gui
import win32api
import ctypes
from mss import mss
from PIL import Image

def get_window_info(window_title):
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd) and window_title.lower() in win32gui.GetWindowText(hwnd).lower():
            windows.append((hwnd, win32gui.GetWindowText(hwnd)))
    windows = []
    win32gui.EnumWindows(callback, windows)
    return windows

def get_window_rect(hwnd):
    window_rect = win32gui.GetWindowRect(hwnd)
    client_rect = win32gui.GetClientRect(hwnd)
    left_border = abs(client_rect[0] - window_rect[0])
    top_border = abs(client_rect[1] - window_rect[1])
    right_border = abs(window_rect[2] - client_rect[2] - left_border)
    bottom_border = abs(window_rect[3] - client_rect[3] - top_border)
    adjusted_rect = (
        window_rect[0] + left_border,
        window_rect[1] + top_border,
        window_rect[2] - right_border,
        window_rect[3] - bottom_border
    )
    return adjusted_rect

def get_scaling_factor():
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetDpiForSystem() / 96.0

def get_mtga_monitor():
    def callback(hwnd, monitors):
        if win32gui.IsWindowVisible(hwnd) and "MTGA" in win32gui.GetWindowText(hwnd):
            monitor = win32api.MonitorFromWindow(hwnd)
            monitors.append(monitor)
    monitors = []
    win32gui.EnumWindows(callback, monitors)
    if not monitors:
        print("MTGA window not found. Defaulting to primary monitor.")
        return None
    return monitors[0]

def capture_fullscreen(mtga_monitor=None):
    with mss() as sct:
        if mtga_monitor:
            monitor_info = win32api.GetMonitorInfo(mtga_monitor)
            monitor = {
                "left": monitor_info["Monitor"][0],
                "top": monitor_info["Monitor"][1],
                "width": monitor_info["Monitor"][2] - monitor_info["Monitor"][0],
                "height": monitor_info["Monitor"][3] - monitor_info["Monitor"][1],
            }
        else:
            monitor = sct.monitors[0]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        img_np = np.array(img)
        return img_np

def preprocess_image(image):
    #gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    #blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    #edges = cv2.Canny(blurred, 50, 150)
    #edges = cv2.Canny(gray, 500, 800)
    #blurred = cv2.GaussianBlur(image, (3, 3), 0)
    lower = (30, 30, 30)  # lower bound for black
    upper = (40, 40, 40)  # upper bound for black (you can adjust this if needed)
    thresh = cv2.inRange(image, lower, upper)    
    return thresh
    #return edges

def find_card_contours(edges):
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours

def filter_card_contours(contours, screenshot_shape):
    screen_height, screen_width = screenshot_shape[:2]
    min_aspect_ratio, max_aspect_ratio = 0.6, 0.8  # Slightly relaxed
    min_rel_width, max_rel_width = 0.06, 0.08
    min_rel_height, max_rel_height = 0.165, 0.18
    #for smaller deck layout, card dimensions ~182x256
    min_rel_width_larger, max_rel_width_larger = 0.09, 0.1
    #for smaller deck layout, card dimensions ~240x340
    min_rel_height_larger, max_rel_height_larger = 0.23, 0.24    
    
    card_contours = []
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
        
        if len(approx) == 4:  # Check if the contour is quadrilateral
            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = w / h
            rel_width = w / screen_width
            rel_height = h / screen_height
            
            if (min_aspect_ratio < aspect_ratio < max_aspect_ratio and
                min_rel_width < rel_width < max_rel_width and
                min_rel_height < rel_height < max_rel_height) or (min_aspect_ratio < aspect_ratio < max_aspect_ratio and
                min_rel_width_larger < rel_width < max_rel_width_larger and
                min_rel_height_larger < rel_height < max_rel_height_larger):
                card_contours.append((x, y, w, h))
    
    return card_contours

def non_max_suppression(boxes, overlapThresh=0.3):
    if len(boxes) == 0:
        return []

    boxes = np.array(boxes)
    pick = []

    x1 = boxes[:,0]
    y1 = boxes[:,1]
    x2 = boxes[:,0] + boxes[:,2]
    y2 = boxes[:,1] + boxes[:,3]

    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)

    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)

        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])

        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)

        overlap = (w * h) / area[idxs[:last]]

        idxs = np.delete(idxs, np.concatenate(([last],
            np.where(overlap > overlapThresh)[0])))

    return boxes[pick].tolist()

def detect_cards(screenshot):
    edges = preprocess_image(screenshot)
    contours = find_card_contours(edges)
    return filter_card_contours(contours, screenshot.shape)

def draw_detected_cards(image, card_positions):
    result_image = image.copy()
    for (x, y, w, h) in card_positions:
        cv2.rectangle(result_image, (x, y), (x+w, y+h), (0, 255, 0), 2)
    return result_image

def save_image(image, filepath):
    cv2.imwrite(filepath, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    #print(f"Image saved as {filepath}")

def sort_card_positions(card_positions):
    # Sort by Y first and then X
    sorted_positions = sorted(card_positions, key=lambda pos: (pos[1], pos[0]))

    # Initialize grouped positions
    grouped_positions = []
    current_group = []
    current_y = None
    tolerance = 3  # Tolerance for grouping positions

    for pos in sorted_positions:
        if current_y is None or abs(pos[1] - current_y) <= tolerance:
            current_group.append(pos)
        else:
            # Sort the current group by X before appending
            grouped_positions.append(sorted(current_group, key=lambda p: p[0]))
            current_group = [pos]  # Start a new group
        current_y = pos[1]

    # Don't forget to add the last group
    if current_group:
        grouped_positions.append(sorted(current_group, key=lambda p: p[0]))

    # Flatten the list of groups while preserving the order
    flattened_positions = [pos for group in grouped_positions for pos in group]
    
    return flattened_positions


def get_card_positions():
    window_title = "MTGA"
    raw_screenshot_path = 'raw_screenshot.png'
    detected_cards_path = 'detected_cards.png'
    preprocessed_screenshot_path = 'preprocessed_screenshot.png'

    try:
        mtga_monitor = get_mtga_monitor()
        mtga_screenshot = capture_fullscreen(mtga_monitor)
        #print(f"Captured full screen image. Dimensions: {mtga_screenshot.shape[1]}x{mtga_screenshot.shape[0]}")
        
        save_image(mtga_screenshot, raw_screenshot_path)
        #print(f"Raw screenshot saved as {raw_screenshot_path}")

        preprocessed = preprocess_image(mtga_screenshot)
        save_image(preprocessed, preprocessed_screenshot_path)

        card_positions = detect_cards(mtga_screenshot)
        #print(f"Found {len(card_positions)} potential card locations")
        #for card_position in card_positions:
            #print(card_position)
        if card_positions is None:
            return None
        result_image = draw_detected_cards(mtga_screenshot, card_positions)
        save_image(result_image, detected_cards_path)

        return sort_card_positions(card_positions)
        #print(card_positions)

    except Exception as e:
        print(f"An error occurred in card_positions: {str(e)}")

def main():
    get_card_positions()

if __name__ == "__main__":
    main()