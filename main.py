import sys
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                             QScrollArea, QLabel, QToolBar, QMessageBox,
                             QWidget, QVBoxLayout)
from PyQt6.QtGui import (QPixmap, QImage, QAction, QColor, QPainter,
                         QPen, QCursor) # Adicionado QPen, QCursor
from PyQt6.QtCore import Qt, QEvent, QTimer, QRect # Adicionado QRect
import os


class PDFPageLabel(QLabel):
    def __init__(self, page_index, main_window):
        super().__init__()
        self.page_index = page_index
        self.main_window = main_window

        # Configurações de Foco e Mouse
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Permite receber teclas (setas)
        self.setMouseTracking(True)

        # Dados de Texto
        self.words = []  # Lista de palavras [(x0, y0, x1, y1, text, ...)]
        self.words_loaded = False

        # Estado da Seleção e Cursor
        self.caret_index = -1  # Onde o cursor piscante está (índice da palavra)
        self.anchor_index = -1  # Onde a seleção começou (âncora)

        # Controle do Piscar (Blink)
        self.caret_visible = False
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(500)  # Pisca a cada 500ms
        self.blink_timer.timeout.connect(self.toggle_caret)

    def load_words_if_needed(self):
        if self.words_loaded or not self.main_window.doc:
            return
        try:
            page = self.main_window.doc.load_page(self.page_index)
            self.words = page.get_text("words")  # (x0, y0, x1, y1, text, ...)
            self.words_loaded = True
        except Exception:
            pass

    def toggle_caret(self):
        """Faz o cursor aparecer/desaparecer"""
        self.caret_visible = not self.caret_visible
        self.update()  # Redesenha para mostrar/esconder

    def get_word_index_at(self, pos):
        """Descobre qual palavra está mais próxima do clique"""
        self.load_words_if_needed()
        if not self.words:
            return -1

        zoom = self.main_window.zoom
        mx, my = pos.x() / zoom, pos.y() / zoom

        # 1. Busca exata
        for i, w in enumerate(self.words):
            if w[0] <= mx <= w[2] and w[1] <= my <= w[3]:
                return i

        # 2. Busca por proximidade (para cliques nas margens ou entre linhas)
        # Encontra a palavra com menor distância Manhattan
        closest_idx = -1
        min_dist = float('inf')

        for i, w in enumerate(self.words):
            # Centro da palavra
            cx = (w[0] + w[2]) / 2
            cy = (w[1] + w[3]) / 2
            dist = abs(cx - mx) + abs(cy - my)
            if dist < min_dist:
                min_dist = dist
                closest_idx = i

        # Limite de distância (opcional, para não selecionar algo do outro lado da página)
        if min_dist < 100:
            return closest_idx
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()  # Importante: Pega o foco para ouvir o teclado!

            idx = self.get_word_index_at(event.pos())
            if idx != -1:
                # Se segurar Shift, estende a seleção a partir da âncora existente
                modifiers = QApplication.keyboardModifiers()
                if modifiers == Qt.KeyboardModifier.ShiftModifier and self.anchor_index != -1:
                    self.caret_index = idx
                else:
                    # Novo clique: reseta âncora e cursor para o mesmo lugar
                    self.anchor_index = idx
                    self.caret_index = idx

                self.caret_visible = True
                self.blink_timer.start()
                self.update()

    def mouseMoveEvent(self, event):
        # Arrastar seleciona texto
        if event.buttons() & Qt.MouseButton.LeftButton:
            idx = self.get_word_index_at(event.pos())
            if idx != -1 and idx != self.caret_index:
                self.caret_index = idx
                self.caret_visible = True  # Mantém visível enquanto arrasta
                self.update()

    def keyPressEvent(self, event):
        """Navegação com teclado (Setas e Cópia)"""
        if not self.words:
            return

        key = event.key()
        modifiers = QApplication.keyboardModifiers()
        shift_pressed = modifiers == Qt.KeyboardModifier.ShiftModifier
        ctrl_pressed = modifiers == Qt.KeyboardModifier.ControlModifier

        if key == Qt.Key.Key_C and ctrl_pressed:
            self.copy_selection()
            return

        # Lógica de Navegação
        new_idx = self.caret_index

        if key == Qt.Key.Key_Left:
            new_idx = max(0, self.caret_index - 1)
        elif key == Qt.Key.Key_Right:
            new_idx = min(len(self.words) - 1, self.caret_index + 1)
        elif key == Qt.Key.Key_Up:
            # Pula ~10 palavras para trás (simulação simples de linha acima)
            new_idx = max(0, self.caret_index - 10)
        elif key == Qt.Key.Key_Down:
            new_idx = min(len(self.words) - 1, self.caret_index + 10)
        else:
            super().keyPressEvent(event)
            return

        # Atualiza estado
        if new_idx != self.caret_index:
            self.caret_index = new_idx

            if not shift_pressed:
                # Se NÃO tem shift, a âncora segue o cursor (sem seleção)
                self.anchor_index = new_idx

            self.caret_visible = True
            self.blink_timer.start()  # Reinicia timer para cursor não sumir enquanto digita
            self.ensure_cursor_visible()
            self.update()

    def ensure_cursor_visible(self):
        """Rola a ScrollArea para seguir o cursor"""
        if 0 <= self.caret_index < len(self.words):
            w = self.words[self.caret_index]
            zoom = self.main_window.zoom
            # Coordenada Y do cursor na widget
            y_pos = w[1] * zoom
            # Altura da viewport
            viewport = self.main_window.scroll_area.viewport()

            # Se cursor estiver saindo da tela, rolar
            current_scroll = self.main_window.scroll_area.verticalScrollBar().value()
            if y_pos < current_scroll:
                self.main_window.scroll_area.verticalScrollBar().setValue(int(y_pos - 20))
            elif y_pos > current_scroll + viewport.height():
                self.main_window.scroll_area.verticalScrollBar().setValue(int(y_pos - viewport.height() + 50))

    def copy_selection(self):
        if self.anchor_index == -1 or self.caret_index == -1:
            return

        start = min(self.anchor_index, self.caret_index)
        end = max(self.anchor_index, self.caret_index)

        selected_words = self.words[start: end + 1]
        text = " ".join([w[4] for w in selected_words])
        QApplication.clipboard().setText(text)
        print("Copiado!")

    def focusOutEvent(self, event):
        """Para o pisca-pisca quando clica fora"""
        self.blink_timer.stop()
        self.caret_visible = False
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # Desenha PDF

        if not self.words or self.caret_index == -1:
            return

        painter = QPainter(self)
        zoom = self.main_window.zoom

        # 1. Desenhar Seleção (Highlight Azul)
        if self.anchor_index != self.caret_index and self.anchor_index != -1:
            start = min(self.anchor_index, self.caret_index)
            end = max(self.anchor_index, self.caret_index)

            painter.setBrush(QColor(0, 120, 215, 80))  # Azul semi-transparente
            painter.setPen(Qt.PenStyle.NoPen)

            for i in range(start, end + 1):
                w = self.words[i]
                rect = QRect(int(w[0] * zoom), int(w[1] * zoom), int((w[2] - w[0]) * zoom), int((w[3] - w[1]) * zoom))
                painter.drawRect(rect)

        # 2. Desenhar Cursor Piscante (Caret)
        if self.hasFocus() and self.caret_visible:
            w = self.words[self.caret_index]

            # Decide onde desenhar: esquerda da palavra (padrão) ou direita (se fim da seleção)
            # Para simplificar, desenhamos sempre à esquerda da palavra atual do caret_index
            cx = int(w[0] * zoom)
            cy_top = int(w[1] * zoom)
            cy_bottom = int(w[3] * zoom)

            # Cor do cursor: Vermelho do tema ou Preto dependendo do fundo
            pen = QPen(QColor("#ff3333"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(cx, cy_top, cx, cy_bottom)

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

            # --- ALTERAÇÃO AQUI ---
            # Antes: label = QLabel()
            # Agora passamos 'i' (índice) e 'self' (a janela principal)
            label = PDFPageLabel(i, self)
            # ----------------------

            label.setFixedSize(width, height)
            # Placeholder style (gray background while loading)
            label.setStyleSheet(f"background-color: {self.get_placeholder_bg_color()}; border: 1px solid #333;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Store the page index in the object for later use
            # label.page_index = i  <-- Não precisa mais setar manualmente, já está no __init__ do PDFPageLabel
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