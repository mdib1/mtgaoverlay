import sys
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import Qt, QObject, pyqtSignal

class OverlaySignals(QObject):
    #show_signal = pyqtSignal(str)
    show_signal = pyqtSignal(str, QtCore.QRect)
    hide_signal = pyqtSignal()
    close_signal = pyqtSignal()

class MainWindow(QMainWindow):
    def __init__(self, message, rect):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.X11BypassWindowManagerHint
        )
        
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.set_position(rect)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)

        self.text_label = QLabel(message, self)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setWordWrap(True)  # Enable word wrapping
        self.text_label.setFixedWidth(rect.width())  # Set a fixed width for the label
        self.text_label.setStyleSheet("""
            color: white; 
            font-size: 24px; 
            background-color: rgba(0, 0, 0, 100);
            padding: 2px;
            border-radius: 5px;
        """)

        # self.close_button = QPushButton("Close", self)
        # self.close_button.setStyleSheet("""
        #     background-color: red;
        #     color: white;
        #     font-size: 18px;
        #     padding: 5px;
        #     border-radius: 3px;
        # """)        
        # self.close_button.clicked.connect(self.close)        

        layout.addWidget(self.text_label)
        #layout.addWidget(self.close_button, alignment=Qt.AlignCenter)        
        self.setCentralWidget(central_widget)

        self.update_text(message)

    def update_text(self, message):
        self.text_label.setText(message)
        #self.text_label.adjustSize()
        #self.adjustSize()

    def set_position(self, rect):
        """Sets the position and size of the window based on the QRect (x, y, width, height)."""
        # Move to the given position (rect.x, rect.y)
        #print(f"Moving to: x={rect.x()}, y={rect.y()}, width={rect.width()}, height={rect.height()}")
        self.move(rect.x(), rect.y())
        # Set the fixed size based on width and height
        self.setFixedSize(rect.width(), rect.height())

class OverlayManager(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.windows = []
        self.signals = OverlaySignals()
        
        self.signals.show_signal.connect(self.show_overlay)

        #self.signals.hide_signal.connect(self.hide_overlay)
        #self.signals.close_signal.connect(self.close_overlay)
        #self.window.close_button.clicked.connect(self.close_overlay)

    def show_overlay(self, message, rect):
        # Create a new overlay window instance for each call
        window = MainWindow(message, rect)
        window.show()
        self.windows.append(window)  # Store the reference

    def show_missing_cards_overlay(self, message):
        screen = QApplication.primaryScreen().geometry()
        rect = QtCore.QRect(0, screen.height() - 200, 300, 200)  # Adjust size as needed
        window = MainWindow(message, rect)
        window.setStyleSheet("background-color: rgba(0, 0, 0, 150);")  # Semi-transparent background
        window.text_label.setStyleSheet("""
            color: white; 
            font-size: 18px; 
            background-color: transparent;
            padding: 2px;
        """)
        #window.close_button.hide()  # Hide the close button for this overlay
        window.show()
        self.windows.append(window)

    #def show_overlay(self, message):
        #self.window.update_text(message)
        #self.window.show()


    def hide_overlay(self):
        for window in self.windows:
            window.hide()

    def run(self):
        self.app.exec_()

    def close_overlay(self):
        for window in self.windows:
            window.close()
        self.app.quit()        


overlay_manager = None

def show_card_overlay(message, card_position):
    rect = QtCore.QRect(*card_position)
    #print("show card overlay at position "+str(card_position))
    get_overlay_manager().signals.show_signal.emit(message, rect)    

def get_overlay_manager():
    global overlay_manager
    if overlay_manager is None:
        overlay_manager = OverlayManager()
    return overlay_manager

def show_overlay(message):
    get_overlay_manager().signals.show_signal.emit(message)

def close_overlay():
    get_overlay_manager().signals.close_signal.emit()

def hide_overlay():
    get_overlay_manager().signals.hide_signal.emit()

def run_overlay():
    get_overlay_manager().run()

def show_missing_cards_overlay(message):
    get_overlay_manager().show_missing_cards_overlay(message)

def show_all_overlays(card_overlays, missing_cards_overlay_string):
    for overlay in card_overlays:
        show_card_overlay(overlay[0],overlay[1])
    if missing_cards_overlay_string != "":
        show_missing_cards_overlay(missing_cards_overlay_string)

if __name__ == '__main__':
    show_overlay("Test Overlay 1")
    run_overlay()