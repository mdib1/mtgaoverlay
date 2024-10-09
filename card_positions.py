import cv2
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

def get_layout_type(screenshot):
    # Check key positions for both layouts
    small_checks = [
        verify_card_position(screenshot, 440, 234, 179, 251),
        verify_card_position(screenshot, 1932, 234, 179, 251),
        verify_card_position(screenshot, 440, 500, 179, 251),
        verify_card_position(screenshot, 1505, 500, 179, 251)
    ]
    max_checks = [
        verify_card_position(screenshot, 366, 240, 240, 338),
        verify_card_position(screenshot, 1414, 240, 240, 338),
        verify_card_position(screenshot, 366, 956, 240, 338),
        verify_card_position(screenshot, 1152, 956, 240, 338)
    ]
    
    small_score = sum(small_checks)
    max_score = sum(max_checks)
    
    if small_score > max_score:
        return 'small'
    elif max_score > small_score:
        return 'maximized'
    else:
        # If scores are equal, use edge detection as a tiebreaker
        small_edges = np.sum(get_edge_image(screenshot[234:485, 440:619]))
        max_edges = np.sum(get_edge_image(screenshot[240:578, 366:606]))
        return 'maximized' if max_edges > small_edges else 'small'

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

def get_edge_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(gray, 50, 150)

def verify_card_position(screenshot, x, y, w, h):
    card_region = screenshot[y:y+h, x:x+w]
    edges = get_edge_image(card_region)
    return np.sum(edges) > 5000  # Adjust threshold as needed    



def detect_cards(screenshot):
    edges = preprocess_image(screenshot)
    contours = find_card_contours(edges)
    return filter_card_contours(contours, screenshot.shape)

def draw_detected_cards(image, card_positions):
    result_image = image.copy()
    for i, (x, y, w, h) in enumerate(card_positions):
        cv2.rectangle(result_image, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(result_image, str(i+1), (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    return result_image

def save_image(image, filepath):
    cv2.imwrite(filepath, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

def get_card_positions(expected_cards, main_thread = False):
    screenshot = capture_mtga_window(main_thread)
    if screenshot is None:
        print("Failed to capture MTGA window")
        return    

    layout_type = get_layout_type(screenshot)
    expected_positions = get_expected_positions(layout_type, expected_cards)
    
    verified_positions = []
    for position in expected_positions:
        if verify_card_position(screenshot, *position):
            verified_positions.append(position)
    
    if len(verified_positions) < expected_cards * 0.7:  # If less than 70% of expected cards are found
        print(f"Warning: Only {len(verified_positions)} out of {expected_cards} expected cards detected. Trying alternative layout.")
        alt_layout_type = 'maximized' if layout_type == 'small' else 'small'
        alt_positions = get_expected_positions(alt_layout_type, expected_cards)
        alt_verified_positions = [pos for pos in alt_positions if verify_card_position(screenshot, *pos)]
        
        if len(alt_verified_positions) > len(verified_positions):
            print(f"Alternative layout ({alt_layout_type}) found more cards. Using this layout instead.")
            verified_positions = alt_verified_positions

    result_image = draw_detected_cards(screenshot, verified_positions)
    #save_image(result_image, 'detected_cards.png')
    #print("Detected cards image saved as 'detected_cards.png'")    
    return verified_positions

def main():
    main_thread = True
    expected_cards = 14
    card_positions = get_card_positions(expected_cards, main_thread)
    print(f"Detected {len(card_positions)} cards out of {expected_cards} expected.")
    for i, pos in enumerate(card_positions):
        print(f"Card {i+1}: {pos}")

if __name__ == "__main__":
    main()