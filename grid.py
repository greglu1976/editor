import sys
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSlider,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFileDialog
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QRectF, QEvent


class GridOverlay(QWidget):
    """Прозрачный виджет поверх QGraphicsView для отрисовки сетки."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_grid_step = 50
        self.grid_scale = 1.0
        
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_grid_scale(self, scale: float):
        self.grid_scale = scale
        self.update()

    def paintEvent(self, event):
        step = self.base_grid_step * self.grid_scale
        if step < 2:
            return

        painter = QPainter(self)
        pen = QPen(QColor(255, 0, 0, 160)) # Полупрозрачный красный
        pen.setWidth(1)
        painter.setPen(pen)

        w = self.width()
        h = self.height()

        x = 0.0
        while x <= w:
            painter.drawLine(int(x), 0, int(x), h)
            x += step
        y = 0.0
        while y <= h:
            painter.drawLine(0, int(y), w, int(y))
            y += step
        painter.end()


class PdfGridWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.pdf_doc = None
        self.pdf_path = ""
        self.current_page = 0
        self.pdf_scale = 1.5
        self.grid_scale = 1.0
        self.is_snapped = False

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self.pdf_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pdf_item)

        # Оверлей
        self.grid_overlay = GridOverlay(self.view)
        self.grid_overlay.setGeometry(self.view.rect())
        self.grid_overlay.raise_()
        self.view.installEventFilter(self)

        # --- UI ---
        self.pdf_zoom_label = QLabel(f"PDF zoom: {self.pdf_scale:.2f}")
        self.grid_zoom_label = QLabel(f"Grid zoom: {self.grid_scale:.2f}")

        self.pdf_slider = QSlider(Qt.Orientation.Horizontal)
        self.pdf_slider.setRange(50, 400)
        self.pdf_slider.setValue(int(self.pdf_scale * 100))
        self.pdf_slider.valueChanged.connect(self.on_pdf_zoom)

        self.grid_slider = QSlider(Qt.Orientation.Horizontal)
        self.grid_slider.setRange(10, 500)
        self.grid_slider.setValue(int(self.grid_scale * 100))
        self.grid_slider.valueChanged.connect(self.on_grid_zoom)

        # Кнопки
        load_btn = QPushButton("Загрузить PDF")
        load_btn.clicked.connect(self.load_pdf)

        self.snap_btn = QPushButton("Snap (Заморозить)")
        self.snap_btn.clicked.connect(self.toggle_snap)

        save_btn = QPushButton("Сохранить PDF с сеткой")
        save_btn.clicked.connect(self.save_pdf_with_grid)

        # Layout
        controls_top = QHBoxLayout()
        controls_top.addWidget(self.pdf_zoom_label)
        controls_top.addWidget(self.pdf_slider)
        controls_top.addWidget(self.grid_zoom_label)
        controls_top.addWidget(self.grid_slider)
        
        controls_bottom = QHBoxLayout()
        controls_bottom.addWidget(load_btn)
        controls_bottom.addWidget(self.snap_btn)
        controls_bottom.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(controls_top)
        layout.addLayout(controls_bottom)
        layout.addWidget(self.view)

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == QEvent.Type.Resize:
            self.grid_overlay.setGeometry(self.view.rect())
            self.grid_overlay.raise_()
        return super().eventFilter(obj, event)

    def load_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите PDF", "", "PDF (*.pdf)")
        if not path:
            return
        self.pdf_path = path
        self.pdf_doc = fitz.open(path)
        self.current_page = 0
        self.render_pdf()

    def render_pdf(self):
        if not self.pdf_doc:
            return
        page = self.pdf_doc[self.current_page]
        matrix = fitz.Matrix(self.pdf_scale, self.pdf_scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        img = QImage(
            pix.samples, pix.width, pix.height,
            pix.stride, QImage.Format.Format_RGB888
        )
        self.pdf_item.setPixmap(QPixmap.fromImage(img))
        self.pdf_item.setPos(0, 0)
        self.scene.setSceneRect(QRectF(0, 0, pix.width, pix.height))

    def on_pdf_zoom(self, value):
        self.pdf_scale = value / 100.0
        self.pdf_zoom_label.setText(f"PDF zoom: {self.pdf_scale:.2f}")
        self.render_pdf()
        
        # Если сетка "заморожена" (Snap), она масштабируется вместе с PDF
        if self.is_snapped:
            self.grid_scale = self.pdf_scale
            self.grid_overlay.set_grid_scale(self.grid_scale)
            self.grid_zoom_label.setText(f"Grid zoom: {self.grid_scale:.2f} (Snapped)")

    def on_grid_zoom(self, value):
        if self.is_snapped:
            return  # Игнорируем, если заморожено
        self.grid_scale = value / 100.0
        self.grid_zoom_label.setText(f"Grid zoom: {self.grid_scale:.2f}")
        self.grid_overlay.set_grid_scale(self.grid_scale)

    def toggle_snap(self):
        self.is_snapped = not self.is_snapped
        if self.is_snapped:
            # Привязываем сетку к текущему масштабу PDF
            self.grid_scale = self.pdf_scale
            self.grid_overlay.set_grid_scale(self.grid_scale)
            
            # Синхронизируем ползунок
            self.grid_slider.blockSignals(True)
            self.grid_slider.setValue(int(self.grid_scale * 100))
            self.grid_slider.blockSignals(False)
            
            self.grid_slider.setEnabled(False)
            self.grid_zoom_label.setText(f"Grid zoom: {self.grid_scale:.2f} (Snapped)")
            self.snap_btn.setText("Unsnap (Разморозить)")
        else:
            self.grid_slider.setEnabled(True)
            self.grid_zoom_label.setText(f"Grid zoom: {self.grid_scale:.2f}")
            self.snap_btn.setText("Snap (Заморозить)")

    def save_pdf_with_grid(self):
        if not self.pdf_doc:
            return
            
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить PDF с сеткой", "", "PDF (*.pdf)")
        if not save_path:
            return

        # Создаем новый PDF
        new_doc = fitz.open()
        
        # Вычисляем шаг сетки в координатах PDF (points)
        # На экране шаг = base_grid_step * grid_scale (в пикселях)
        # Чтобы перевести в points PDF, делим на pdf_scale
        step_in_pdf_points = (self.grid_overlay.base_grid_step * self.grid_scale) / self.pdf_scale
        
        if step_in_pdf_points < 1:
            step_in_pdf_points = 1 # Защита от слишком частой сетки

        for page_num in range(len(self.pdf_doc)):
            src_page = self.pdf_doc[page_num]
            
            # Копируем страницу в новый документ
            new_page = new_doc.new_page(width=src_page.rect.width, height=src_page.rect.height)
            new_page.show_pdf_page(new_page.rect, self.pdf_doc, page_num)
            
            # Рисуем сетку
            shape = new_page.new_shape()
            # Цвет: красный (R=1, G=0, B=0), прозрачность ~0.6
            color = (1, 0, 0)
            
            # Вертикальные линии
            x = 0
            while x <= new_page.rect.width:
                shape.draw_line(fitz.Point(x, 0), fitz.Point(x, new_page.rect.height))
                x += step_in_pdf_points
                
            # Горизонтальные линии
            y = 0
            while y <= new_page.rect.height:
                shape.draw_line(fitz.Point(0, y), fitz.Point(new_page.rect.width, y))
                y += step_in_pdf_points
            
            shape.finish(color=color, width=0.5, stroke_opacity=0.5)
            shape.commit()

        new_doc.save(save_path)
        new_doc.close()
        print(f"Сохранено: {save_path}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF + сетка: Snap & Save")
        self.resize(1100, 800)
        self.setCentralWidget(PdfGridWidget())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())