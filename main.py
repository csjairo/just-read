import sys
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                             QScrollArea, QLabel, QToolBar, QMessageBox,
                             QWidget, QVBoxLayout)
from PyQt6.QtGui import QPixmap, QImage, QAction, QColor, QPainter
from PyQt6.QtCore import Qt, QEvent, QTimer
import os


class JustReadApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Just Read - Optimized PDF Reader")
        self.setMinimumSize(900, 700)

        # State Variables
        self.doc = None
        self.zoom = 1.0
        self.view_mode = "normal"
        self.page_labels = []

        # Timer to prevent rendering while the user is still scrolling frantically
        self.scroll_timer = QTimer()
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.setInterval(50)  # Wait 50ms after stopping scroll
        self.scroll_timer.timeout.connect(self.update_page_visibility)

        self.init_ui()

    def init_ui(self):
        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Monitor the scroll bar
        self.scroll_bar = self.scroll_area.verticalScrollBar()
        self.scroll_bar.valueChanged.connect(self.on_scroll)

        # Vertical Container
        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setSpacing(20)
        self.pages_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.scroll_area.setWidget(self.pages_container)
        self.setCentralWidget(self.scroll_area)

        # Event Filter (Zoom)
        self.scroll_area.viewport().installEventFilter(self)

        # Toolbar
        toolbar = QToolBar("Tools")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # Actions
        btn_open = QAction("📂 Open", self)
        btn_open.triggered.connect(self.open_file)
        toolbar.addAction(btn_open)

        toolbar.addSeparator()

        btn_zoom_in = QAction("🔍➕", self)
        btn_zoom_in.triggered.connect(self.zoom_in)
        toolbar.addAction(btn_zoom_in)

        btn_zoom_out = QAction("🔍➖", self)
        btn_zoom_out.triggered.connect(self.zoom_out)
        toolbar.addAction(btn_zoom_out)

        toolbar.addSeparator()

        btn_normal = QAction("Normal", self)
        btn_normal.triggered.connect(lambda: self.change_mode("normal"))
        toolbar.addAction(btn_normal)

        btn_dark = QAction("Inverted", self)
        btn_dark.triggered.connect(lambda: self.change_mode("dark"))
        toolbar.addAction(btn_dark)

        btn_night = QAction("Night", self)
        btn_night.triggered.connect(lambda: self.change_mode("night"))
        toolbar.addAction(btn_night)

    def eventFilter(self, source, event):
        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            modifiers = QApplication.keyboardModifiers()
            if modifiers == Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True
        return super().eventFilter(source, event)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if file_path:
            try:
                self.doc = fitz.open(file_path)
                self.zoom = 1.0
                self.setup_placeholders()  # Configures empty spaces
                self.update_page_visibility()  # Renders only what is visible
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error opening file:\n{e}")

    def setup_placeholders(self):
        """Creates empty labels with the exact size the page will have, without rendering the image."""
        # Clear previous layout
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.page_labels = []

        if not self.doc:
            return

        for i, page in enumerate(self.doc):
            # Calculate the size the page WOULD have if rendered
            rect = page.rect  # Original size (points)
            width = int(rect.width * self.zoom)
            height = int(rect.height * self.zoom)

            label = QLabel()
            label.setFixedSize(width, height)  # Reserves layout memory, not video memory
            # Placeholder style (gray background while loading)
            label.setStyleSheet(f"background-color: {self.get_placeholder_bg_color()}; border: 1px solid #333;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Store the page index in the object for later use
            label.page_index = i
            label.is_rendered = False  # Flag for control

            self.pages_layout.addWidget(label)
            self.page_labels.append(label)

    def on_scroll(self):
        # Uses a timer to avoid processing every single scrolled pixel (debounce)
        self.scroll_timer.start()

    def update_page_visibility(self):
        """The heart of optimization: Detects what is on screen and renders/clears."""
        if not self.doc:
            return

        # Visible area geometry (Viewport)
        scroll_y = self.scroll_bar.value()
        viewport_height = self.scroll_area.viewport().height()
        min_y = scroll_y - viewport_height  # Safety margin above
        max_y = scroll_y + (viewport_height * 2)  # Safety margin below

        for label in self.page_labels:
            # Y position of the label inside the container
            label_y = label.y()
            label_height = label.height()

            # Check intersection: Is the label inside the visible area (with margin)?
            is_visible = (label_y + label_height > min_y) and (label_y < max_y)

            if is_visible:
                if not label.is_rendered:
                    self.render_single_page(label)
            else:
                if label.is_rendered:
                    self.clear_single_page(label)

    def render_single_page(self, label):
        """Renders and allocates memory for ONE page."""
        idx = label.page_index
        page = self.doc.load_page(idx)
        matrix = fitz.Matrix(self.zoom, self.zoom)

        # Heavy rendering happens here
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        fmt = QImage.Format.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)

        img = self.apply_image_filter(img)

        label.setPixmap(QPixmap.fromImage(img))
        label.is_rendered = True
        # Remove placeholder style
        label.setStyleSheet("background-color: transparent;")

    def clear_single_page(self, label):
        """Removes the image from RAM."""
        label.setPixmap(QPixmap())  # Clears texture
        label.setText("")  # Removes text if any
        label.is_rendered = False
        # Reverts to placeholder background color
        label.setStyleSheet(f"background-color: {self.get_placeholder_bg_color()}; border: 1px solid #333;")

    def apply_image_filter(self, img):
        if self.view_mode == "dark":
            img.invertPixels(QImage.InvertMode.InvertRgb)
        elif self.view_mode == "night":
            painter = QPainter(img)
            overlay_color = QColor(255, 140, 0, 80)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillRect(img.rect(), overlay_color)
            painter.end()
        return img

    def get_placeholder_bg_color(self):
        if self.view_mode == "dark":
            return "#333333"
        if self.view_mode == "night":
            return "#4d4030"
        return "#cccccc"

    def change_mode(self, mode):
        self.view_mode = mode
        # Force re-rendering of visible pages
        for label in self.page_labels:
            if label.is_rendered:
                self.render_single_page(label)
            else:
                # Update placeholder color for non-rendered pages
                label.setStyleSheet(f"background-color: {self.get_placeholder_bg_color()}; border: 1px solid #333;")

    def zoom_in(self):
        self.zoom += 0.2
        self.apply_new_zoom()

    def zoom_out(self):
        if self.zoom > 0.4:
            self.zoom -= 0.2
            self.apply_new_zoom()

    def apply_new_zoom(self):
        """When zooming, we need to resize placeholders and re-render what is visible."""
        if not self.doc:
            return

        # 1. Update size of ALL placeholders (fast, geometry only)
        for label in self.page_labels:
            page = self.doc.load_page(label.page_index)
            rect = page.rect
            width = int(rect.width * self.zoom)
            height = int(rect.height * self.zoom)
            label.setFixedSize(width, height)
            label.is_rendered = False  # Mark as dirty for re-rendering

        # 2. Render only visible pages at new size
        self.update_page_visibility()


# --- Style Function ---
def load_dark_red_style(app):
    qss_file = os.path.join(os.path.dirname(__file__), "style.qss")
    try:
        with open(qss_file, "r", encoding="utf-8") as f:
            style = f.read()
            app.setStyleSheet(style)
    except FileNotFoundError:
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_dark_red_style(app)
    window = JustReadApp()
    window.show()
    sys.exit(app.exec())