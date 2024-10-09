import cv2
import math
import numpy as np
import win32gui
import win32api
from mss import mss
from PIL import Image
import win32ui
import win32con
import ctypes
from ctypes import windll
from statistics import median

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
    #print(flattened_positions)
    return flattened_positions

def capture_mtga_window(main_thread):
    hwnd = win32gui.FindWindow(None, "MTGA")
    if not hwnd:
        print("MTGA window not found")
        return None

    left, top, right, bot = win32gui.GetClientRect(hwnd)
    width = right - left
    height = bot - top

    if(main_thread):
        # Account for display scaling
        try:
            # Get the window DPI scaling factor
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            dpi = user32.GetDpiForWindow(hwnd)
            scale_factor = dpi / 96.0

            # Adjust the width and height
            width = int(width * scale_factor)
            height = int(height * scale_factor)
        except:
            print("Failed to adjust for DPI scaling. Using unadjusted size.")

    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
    saveDC.SelectObject(saveBitMap)

    result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)

    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)

    im = Image.frombuffer(
        'RGB',
        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
        bmpstr, 'raw', 'BGRX', 0, 1)

    img_np = np.array(im)

    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)

    return img_np if result == 1 else None

def get_expected_positions(layout_type, num_cards):
    if layout_type == 'small':
        positions = [
            (440, 234, 179, 251), (653, 234, 179, 251), (866, 234, 179, 251),
            (1079, 234, 179, 251), (1292, 234, 179, 251), (1505, 234, 178, 251),
            (1719, 234, 179, 251), (1932, 234, 179, 251),
            (440, 500, 179, 251), (653, 500, 179, 251), (866, 500, 179, 251),
            (1079, 500, 179, 251), (1292, 500, 179, 251), (1505, 500, 179, 251)
        ]
    else:  # maximized
        positions = [
            (366, 240, 240, 338), (628, 240, 240, 338), (890, 240, 240, 338),
            (1152, 240, 240, 338), (1414, 240, 240, 338),
            (366, 598, 240, 338), (628, 598, 240, 338), (890, 598, 240, 338),
            (1152, 598, 240, 338), (1414, 598, 240, 338),
            (366, 956, 240, 338), (628, 956, 240, 338), (890, 956, 240, 338),
            (1152, 956, 240, 338)
        ]
    return positions[:num_cards]

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

# def filter_card_contours(contours, screenshot_shape):
#     screen_height, screen_width = screenshot_shape[:2]
#     min_aspect_ratio, max_aspect_ratio = 0.6, 0.8  # Slightly relaxed
#     card_contours = []
#     for contour in contours:
#         peri = cv2.arcLength(contour, True)
#         approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
#         if len(approx) == 4:  # Check if the contour is quadrilateral
#             x, y, w, h = cv2.boundingRect(approx)
#             aspect_ratio = w / h
#             rel_width = w / screen_width
#             rel_height = h / screen_height
#             if min_aspect_ratio < aspect_ratio < max_aspect_ratio:
#                 card_contours.append((x, y, w, h))
#     return card_contours

def detect_cards(screenshot):
    contours = find_card_contours(screenshot)
    min_area_rects = []
    for contour in contours:
        rect = cv2.minAreaRect(contour)
        min_area_rects.append(rect)    
    try:
        largest_contour = max(contours, key=cv2.contourArea)
    except:
        return None
    min_area_rect = cv2.minAreaRect(largest_contour)
    box = cv2.boxPoints(min_area_rect)
    box = np.int0(box)
    return box

def draw_detected_cards(image, card_positions):
    result_image = image.copy()
    for (x, y, w, h) in card_positions:
        cv2.rectangle(result_image, (x, y), (x+w, y+h), (0, 255, 0), 2)
    return result_image

def rect_to_box(rect):
    x, y, w, h = rect
    return [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]


def box_to_rect(box):
    x = min(point[0] for point in box)
    y = min(point[1] for point in box)
    w = max(point[0] for point in box) - x
    h = max(point[1] for point in box) - y
    return (x, y, w, h)

def save_image(image, filepath):
    cv2.imwrite(filepath, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

def rect_area(rect):
    _, _, w, h = rect
    return w * h

def get_card_positions(expected_cards, input_image_file_path=None, main_thread=False, debug=False):
    raw_screenshot_path = 'raw_screenshot.png'
    detected_cards_path = 'detected_cards.png'
    preprocessed_screenshot_path = 'preprocessed_screenshot.png'    

    if input_image_file_path is None:
        mtga_screenshot = capture_mtga_window(main_thread)
        if mtga_screenshot is None:
            print("Failed to capture MTGA window")
            return None
    else:
        mtga_screenshot = cv2.imread(input_image_file_path)
        if mtga_screenshot is None:
            print(f"Failed to load image from {input_image_file_path}")
            return None

    #save_image(mtga_screenshot, raw_screenshot_path)
    #print(f"Raw screenshot saved as {raw_screenshot_path}")

    preprocessed = preprocess_image(mtga_screenshot)
    #save_image(preprocessed, preprocessed_screenshot_path)

    small_layout = get_expected_positions("small", expected_cards)
    large_layout = get_expected_positions("large", expected_cards)

    small_layout_detected_cards = []
    large_layout_detected_cards = []

    def detect_card_at_position(position, layout_name, index):
        x, y, w, h = position
        cropped_image = mtga_screenshot[y:y+h, x:x+w]
        preprocessed_cropped_image = preprocessed[y:y+h, x:x+w].copy()
        detection_filename = f'{layout_name}_card_detection_{index}.png'
        #save_image(preprocessed_cropped_image, detection_filename)
        screenshot = preprocessed_cropped_image

        box = detect_cards(screenshot)
        if box is None:
            return None
        card_position = box_to_rect(box)
        #print("found "+str(len(card_positions))+" viable card positions")
        #card_position = card_positions[0]
        # Draw a rectangle around the entire cropped image
        x, y, w, h = card_position
        cv2.rectangle(cropped_image, (x, y), (x + w - 1, y + h - 1), (0, 255, 0))


        detection_filename = f'{layout_name}_card_detection_{index}_rectdrawn.png'
        #save_image(cropped_image, detection_filename)        
        
        #print(f"Saved detection image for {layout_name} layout, position {index} as {detection_filename}")
        
        return card_position

    sum_small_layout_discrepancy = 0
    sum_large_layout_discrepancy = 0

    for i, position in enumerate(small_layout):
        detected_card_position = detect_card_at_position(position, 'small', i)
        if detected_card_position:
            area_difference = rect_area(position) - rect_area(detected_card_position)
            sum_small_layout_discrepancy += abs(area_difference)
            small_layout_detected_cards.append(position)

    for i, position in enumerate(large_layout):
        detected_card_position = detect_card_at_position(position, 'large', i)
        if detected_card_position:
            area_difference = rect_area(position) - rect_area(detected_card_position)
            sum_large_layout_discrepancy += abs(area_difference)            
            large_layout_detected_cards.append(position)

    #print("sum_small_layout_discrepancy: "+str(sum_small_layout_discrepancy))
    #print("sum_large_layout_discrepancy: "+str(sum_large_layout_discrepancy))
    #print(f"Detected {len(small_layout_detected_cards)} cards in small layout")
    #print(f"Detected {len(large_layout_detected_cards)} cards in large layout")

    # Decide which layout to use based on the number of detected cards
    # if len(small_layout_detected_cards) > len(large_layout_detected_cards):
    #     final_card_positions = small_layout_detected_cards
    #     print("Using small layout")
    # else:
    #     final_card_positions = large_layout_detected_cards
    #     print("Using large layout")

    # result_image = draw_detected_cards(mtga_screenshot, final_card_positions)
    # save_image(result_image, detected_cards_path)

    # return sort_card_positions(final_card_positions)

    small_layout_image = draw_detected_cards(mtga_screenshot, small_layout_detected_cards)
    large_layout_image = draw_detected_cards(mtga_screenshot, large_layout_detected_cards)

    small_layout_path = 'small_layout_detected_cards.png'
    large_layout_path = 'large_layout_detected_cards.png'

    #save_image(small_layout_image, small_layout_path)
    #save_image(large_layout_image, large_layout_path)

    #print(f"Small layout detected cards saved as {small_layout_path}")
    #print(f"Large layout detected cards saved as {large_layout_path}")

    if sum_small_layout_discrepancy < sum_large_layout_discrepancy:
        #print("using small layout")
        return small_layout_detected_cards
    else:
        #print("using large layout")
        return large_layout_detected_cards
# def get_card_positions(expected_cards, input_image_file_path = None, main_thread = False, debug=False):

#     raw_screenshot_path = 'raw_screenshot.png'
#     detected_cards_path = 'detected_cards.png'
#     preprocessed_screenshot_path = 'preprocessed_screenshot.png'    

#     if input_image_file_path is None:
#         mtga_screenshot = capture_mtga_window(main_thread)
#         if mtga_screenshot is None:
#             print("Failed to capture MTGA window")
#             return    
#     else:
#         #load input_image_file_path instead of taking screenshot 
#         mtga_screenshot = cv2.imread(input_image_file_path)
#         if mtga_screenshot is None:
#             print(f"Failed to load image from {input_image_file_path}")
#             return

#     #print(f"Captured full screen image. Dimensions: {mtga_screenshot.shape[1]}x{mtga_screenshot.shape[0]}")
    
#     save_image(mtga_screenshot, raw_screenshot_path)
#     print(f"Raw screenshot saved as {raw_screenshot_path}")

#     preprocessed = preprocess_image(mtga_screenshot)
#     save_image(preprocessed, preprocessed_screenshot_path)

#     card_positions = detect_cards(mtga_screenshot)
#     print(f"Found {len(card_positions)} potential card locations")
#     for card_position in card_positions:
#         print(card_position)
#     if card_positions is None:
#         return None
#     small_layout = get_expected_positions("small", expected_cards)
#     large_layout = get_expected_positions("large", expected_cards)
#     total_distance_for_large_layout = 0
#     total_distance_for_small_layout = 0
#     for i in range(len(card_positions)):
#         total_distance_for_small_layout += calculate_distance(small_layout[i], card_positions[i])
#         total_distance_for_large_layout += calculate_distance(large_layout[i], card_positions[i])
#     print("total_distance_for_small_layout "+str(total_distance_for_small_layout))
#     print("total_distance_for_large_layout "+str(total_distance_for_large_layout))
#     if total_distance_for_small_layout < total_distance_for_large_layout:
#         card_positions = small_layout
#     result_image = draw_detected_cards(mtga_screenshot, card_positions)
#     save_image(result_image, detected_cards_path)
#     print(card_positions)
#     return sort_card_positions(card_positions)

def calculate_distance(pos1, pos2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(pos1, pos2)))

def main():
    main_thread = True
    expected_cards = 9
    input_image_file_path = "inputscreenshot.png"
    useMTGA = None
    #card_positions = get_card_positions(expected_cards, input_image_file_path, main_thread)
    card_positions = get_card_positions(expected_cards, useMTGA, main_thread)
    if card_positions:
        print(f"Detected {len(card_positions)} cards out of {expected_cards} expected.")
        for i, pos in enumerate(card_positions):
            print(f"Card {i+1}: {pos}")
    else:
        print("Failed to detect cards.")

if __name__ == "__main__":
    main()