import sys
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import Qt, QObject, pyqtSignal

class OverlaySignals(QObject):
    show_signal = pyqtSignal(str)
    hide_signal = pyqtSignal()
    close_signal = pyqtSignal()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.X11BypassWindowManagerHint
        )
        
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        
        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        
        self.text_label = QLabel("", self)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet("""
            color: white; 
            font-size: 24px; 
            background-color: rgba(0, 0, 0, 100);
            padding: 10px;
            border-radius: 5px;
        """)

        self.close_button = QPushButton("Close", self)
        self.close_button.setStyleSheet("""
            background-color: red;
            color: white;
            font-size: 18px;
            padding: 5px;
            border-radius: 3px;
        """)        
        self.close_button.clicked.connect(self.close)        
        
        layout.addWidget(self.text_label)
        layout.addWidget(self.close_button, alignment=Qt.AlignCenter)        
        self.setCentralWidget(central_widget)

    def update_text(self, message):
        self.text_label.setText(message)
        self.text_label.adjustSize()
        self.adjustSize()

class OverlayManager(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.window = MainWindow()
        self.signals = OverlaySignals()
        
        self.signals.show_signal.connect(self.show_overlay)
        self.signals.hide_signal.connect(self.hide_overlay)
        self.signals.close_signal.connect(self.close_overlay)

        self.window.close_button.clicked.connect(self.close_overlay)

    def show_overlay(self, message):
        self.window.update_text(message)
        self.window.show()

    def hide_overlay(self):
        self.window.hide()

    def run(self):
        self.app.exec_()

    def close_overlay(self):
        self.window.close()
        self.app.quit()        


overlay_manager = None

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

if __name__ == '__main__':
    show_overlay("Test Overlay 1")
    run_overlay()