import sys
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                             QScrollArea, QLabel, QToolBar, QMessageBox,
                             QWidget, QVBoxLayout)
from PyQt6.QtGui import QPixmap, QImage, QAction, QColor, QPainter
from PyQt6.QtCore import Qt, QEvent, QTimer
import os


class LeitorPDFOtimizado(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Leitor PDF - Otimizado (Lazy Loading)")
        self.setMinimumSize(900, 700)

        # Variáveis de Estado
        self.doc = None
        self.zoom = 1.0
        self.modo_visualizacao = "normal"
        self.labels_paginas = []

        # Timer para evitar renderizar enquanto o usuário ainda está rolando freneticamente
        self.timer_scroll = QTimer()
        self.timer_scroll.setSingleShot(True)
        self.timer_scroll.setInterval(50)  # Espera 50ms após parar de rolar
        self.timer_scroll.timeout.connect(self.atualizar_visibilidade_paginas)

        self.init_ui()

    def init_ui(self):
        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Monitorar a barra de rolagem
        self.scroll_bar = self.scroll_area.verticalScrollBar()
        self.scroll_bar.valueChanged.connect(self.ao_rolar)

        # Container Vertical
        self.container_paginas = QWidget()
        self.layout_paginas = QVBoxLayout(self.container_paginas)
        self.layout_paginas.setSpacing(20)
        self.layout_paginas.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.scroll_area.setWidget(self.container_paginas)
        self.setCentralWidget(self.scroll_area)

        # Filtro de Eventos (Zoom)
        self.scroll_area.viewport().installEventFilter(self)

        # Barra de Ferramentas
        toolbar = QToolBar("Ferramentas")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # Ações
        btn_abrir = QAction("📂 Abrir", self)
        btn_abrir.triggered.connect(self.abrir_arquivo)
        toolbar.addAction(btn_abrir)

        toolbar.addSeparator()

        btn_zoom_in = QAction("🔍➕", self)
        btn_zoom_in.triggered.connect(self.aumentar_zoom)
        toolbar.addAction(btn_zoom_in)

        btn_zoom_out = QAction("🔍➖", self)
        btn_zoom_out.triggered.connect(self.diminuir_zoom)
        toolbar.addAction(btn_zoom_out)

        toolbar.addSeparator()

        btn_normal = QAction("Normal", self)
        btn_normal.triggered.connect(lambda: self.mudar_modo("normal"))
        toolbar.addAction(btn_normal)

        btn_dark = QAction("Invertido", self)
        btn_dark.triggered.connect(lambda: self.mudar_modo("dark"))
        toolbar.addAction(btn_dark)

        btn_night = QAction("Noturno", self)
        btn_night.triggered.connect(lambda: self.mudar_modo("night"))
        toolbar.addAction(btn_night)

    def eventFilter(self, source, event):
        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            modifiers = QApplication.keyboardModifiers()
            if modifiers == Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.aumentar_zoom()
                else:
                    self.diminuir_zoom()
                return True
        return super().eventFilter(source, event)

    def abrir_arquivo(self):
        caminho, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "Arquivos PDF (*.pdf)")
        if caminho:
            try:
                self.doc = fitz.open(caminho)
                self.zoom = 1.0
                self.setup_placeholders()  # Configura espaços vazios
                self.atualizar_visibilidade_paginas()  # Renderiza só o que está visível
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao abrir:\n{e}")

    def setup_placeholders(self):
        """Cria labels vazios com o tamanho exato que a página terá, sem renderizar a imagem."""
        # Limpar layout anterior
        while self.layout_paginas.count():
            item = self.layout_paginas.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.labels_paginas = []

        if not self.doc: return

        matriz = fitz.Matrix(self.zoom, self.zoom)

        for i, page in enumerate(self.doc):
            # Calculamos o tamanho que a página TERIA se fosse renderizada
            rect = page.rect  # Tamanho original (pontos)
            width = int(rect.width * self.zoom)
            height = int(rect.height * self.zoom)

            label = QLabel()
            label.setFixedSize(width, height)  # Reserva o espaço na memória de layout, não de vídeo
            # Estilo placeholder (fundo cinza enquanto carrega)
            label.setStyleSheet(f"background-color: {self.obter_cor_fundo_placeholder()}; border: 1px solid #333;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Guardamos o índice da página no objeto para uso posterior
            label.page_index = i
            label.is_rendered = False  # Flag para controle

            self.layout_paginas.addWidget(label)
            self.labels_paginas.append(label)

    def ao_rolar(self):
        # Usa um timer para não processar a cada pixel rolado (debounce)
        self.timer_scroll.start()

    def atualizar_visibilidade_paginas(self):
        """O coração da otimização: Descobre o que está na tela e renderiza/limpa."""
        if not self.doc: return

        # Geometria da área visível (Viewport)
        scroll_y = self.scroll_bar.value()
        viewport_height = self.scroll_area.viewport().height()
        min_y = scroll_y - viewport_height  # Margem de segurança acima
        max_y = scroll_y + (viewport_height * 2)  # Margem de segurança abaixo

        for label in self.labels_paginas:
            # Posição Y do label dentro do container
            label_y = label.y()
            label_height = label.height()

            # Verifica intersecção: O label está dentro da área visível (com margem)?
            visivel = (label_y + label_height > min_y) and (label_y < max_y)

            if visivel:
                if not label.is_rendered:
                    self.renderizar_pagina_unica(label)
            else:
                if label.is_rendered:
                    self.limpar_pagina_unica(label)

    def renderizar_pagina_unica(self, label):
        """Renderiza e aloca memória para UMA página."""
        idx = label.page_index
        page = self.doc.load_page(idx)
        matriz = fitz.Matrix(self.zoom, self.zoom)

        # Renderização pesada acontece aqui
        pix = page.get_pixmap(matrix=matriz, alpha=False)
        fmt = QImage.Format.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)

        img = self.aplicar_filtro_imagem(img)

        label.setPixmap(QPixmap.fromImage(img))
        label.is_rendered = True
        # Remove o estilo de placeholder
        label.setStyleSheet("background-color: transparent;")

    def limpar_pagina_unica(self, label):
        """Remove a imagem da RAM."""
        label.setPixmap(QPixmap())  # Limpa a textura
        label.setText("")  # Remove texto se tiver
        label.is_rendered = False
        # Volta a cor de fundo do placeholder
        label.setStyleSheet(f"background-color: {self.obter_cor_fundo_placeholder()}; border: 1px solid #333;")

    def aplicar_filtro_imagem(self, img):
        if self.modo_visualizacao == "dark":
            img.invertPixels(QImage.InvertMode.InvertRgb)
        elif self.modo_visualizacao == "night":
            painter = QPainter(img)
            overlay_color = QColor(255, 140, 0, 80)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillRect(img.rect(), overlay_color)
            painter.end()
        return img

    def obter_cor_fundo_placeholder(self):
        if self.modo_visualizacao == "dark": return "#333333"
        if self.modo_visualizacao == "night": return "#4d4030"
        return "#cccccc"

    def mudar_modo(self, modo):
        self.modo_visualizacao = modo
        # Força re-renderização das visíveis
        for label in self.labels_paginas:
            if label.is_rendered:
                self.renderizar_pagina_unica(label)
            else:
                # Atualiza cor do placeholder dos não renderizados
                label.setStyleSheet(f"background-color: {self.obter_cor_fundo_placeholder()}; border: 1px solid #333;")

    def aumentar_zoom(self):
        self.zoom += 0.2
        self.aplicar_novo_zoom()

    def diminuir_zoom(self):
        if self.zoom > 0.4:
            self.zoom -= 0.2
            self.aplicar_novo_zoom()

    def aplicar_novo_zoom(self):
        """Ao dar zoom, precisamos redimensionar os placeholders e re-renderizar o que é visível."""
        if not self.doc: return

        # 1. Atualiza tamanho de TODOS os placeholders (rápido, só geometria)
        for label in self.labels_paginas:
            page = self.doc.load_page(label.page_index)
            rect = page.rect
            width = int(rect.width * self.zoom)
            height = int(rect.height * self.zoom)
            label.setFixedSize(width, height)
            label.is_rendered = False  # Marca como sujo para re-renderizar

        # 2. Renderiza apenas os visíveis no novo tamanho
        self.atualizar_visibilidade_paginas()


# --- Função de Estilo (Mantenha a mesma anterior) ---
def carregar_estilo_dark_red(app):
    qss_file = os.path.join(os.path.dirname(__file__), "style.qss")
    try:
        with open(qss_file, "r", encoding="utf-8") as f:
            style = f.read()
            app.setStyleSheet(style)
    except FileNotFoundError:
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    carregar_estilo_dark_red(app)
    window = LeitorPDFOtimizado()
    window.show()
    sys.exit(app.exec())
