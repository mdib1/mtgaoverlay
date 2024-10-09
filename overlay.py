import sys
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QRect, pyqtSlot
import ctypes

class OverlayWidget(QWidget):
    def __init__(self, message, rect, parent=None):
        super().__init__(parent)
        self.setGeometry(rect)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.layout = QVBoxLayout(self)
        self.text_label = QLabel(message, self)
        self.layout.addWidget(self.text_label)
        
        self.update_widget(message, rect)
        self.show()
        #print(f"OverlayWidget created and shown: {self.geometry()}")        

    def paintEvent(self, event):
        #print(f"Paint event for OverlayWidget: {self.geometry()}")
        super().paintEvent(event)

    def show(self):
        super().show()
        #print(f"OverlayWidget show called: {self.geometry()}")

    def update_widget(self, message, rect):
        self.setGeometry(rect)
        self.text_label.setText(message)
        self.text_label.setGeometry(self.rect())
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setStyleSheet("""
            color: white;             
            background-color: rgba(0, 0, 0, 100);  
        """)
        self.layout.setContentsMargins(0,0,0,0)
        self.layout.setSpacing(0)        
        self.update()
        #print(f"OverlayWidget updated: {message[:20]}... at {rect}")          

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTGA Draft Overlay")
        self.screen = QApplication.primaryScreen().geometry()
        self.missing_cards_overlay = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCentralWidget(QWidget())  # Dummy widget to allow overlays

        self.overlays = {}
        print("MainWindow initialized")           

    def hide_missing_cards_overlay(self):
        if self.missing_cards_overlay:
            self.missing_cards_overlay.hide()

    def show_missing_cards_overlay(self, message):

        rect = QtCore.QRect(self.screen.width() - 300, self.screen.height() - 400, 300, 400)        
        if self.missing_cards_overlay is None:
            self.missing_cards_overlay = OverlayWidget(message, rect, self) 
        else:
            self.missing_cards_overlay.update_widget(message, rect)

    def show_overlay(self, overlay_id, message, rect):
        if overlay_id in self.overlays:
            self.overlays[overlay_id].update_widget(message, rect)
        else:
            overlay = OverlayWidget(message, rect, self)
            self.overlays[overlay_id] = overlay
        self.overlays[overlay_id].show()
        #print(f"Overlay {overlay_id} should be visible now: {rect}")            

    def mark_overlay_for_deletion(self, overlay):
        overlay.setParent(None)
        overlay.deleteLater()

    def show_all_overlays(self, card_overlays, missing_cards_overlay_string):
        n = len(self.overlays) - len(card_overlays)
        if n > 0:
            print(f"Received {n} fewer cards this time")
            overlays_list = list(self.overlays.values())  # Convert dict values to list
            
            overlays_keys_to_be_removed = list(self.overlays.keys())[-n:]

            for key in overlays_keys_to_be_removed:
                overlay = self.overlays[key]
                print("remove overlay " + str(overlay))
                print(str(len(self.overlays))+" overlays to begin with")                
                self.mark_overlay_for_deletion(overlay)
                del self.overlays[key]  # Remove the overlay from the dictionary
                print(str(len(self.overlays))+" overlays after removal of one")                

        #print(f"Showing all overlays: {len(card_overlays)} cards")
        for i, overlay in enumerate(card_overlays):
            self.show_overlay(f"card_{i}", overlay[0], QRect(*overlay[1]))
        if missing_cards_overlay_string:
            self.show_missing_cards_overlay(missing_cards_overlay_string)
        else:
            self.hide_missing_cards_overlay()
        self.update()  # This calls update on the MainWindow
        #print("All overlays should be visible now")


    def show(self):
        super().show()
        #print(f"MainWindow shown: {self.geometry()}")

    def paintEvent(self, event):
        #print("MainWindow paint event")
        super().paintEvent(event)        

class OverlayManager(QObject):
    overlay_update_signal = pyqtSignal(str, str, QRect)
    hide_overlay_signal = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.main_window = MainWindow()

    @pyqtSlot(list, str)
    def show_all_overlays(self, card_overlays, missing_cards_overlay_string):
        self.main_window.show_all_overlays(card_overlays, missing_cards_overlay_string)

    def run(self):
        self.main_window.show()
