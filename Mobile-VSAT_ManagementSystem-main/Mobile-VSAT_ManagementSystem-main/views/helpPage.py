# views/helpPage.py - Embedded PDF viewer using PyMuPDF
import os
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError as e:
    print(f"DEBUG: Failed to import fitz: {e}")
    HAS_PYMUPDF = False

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QScrollArea, QSpinBox, QMessageBox
)

from components.utils import resource_path


class HelpPage(QWidget):
    """Embedded PDF Viewer for Manual.pdf"""
    
    def __init__(self):
        super().__init__()
        
        self.current_page = 0
        self.pdf_document = None
        self.zoom_level = 1.5  # Scale factor for better readability
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Top toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 10, 10, 10)
        toolbar.setSpacing(10)
        
        # Page navigation
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.clicked.connect(self._prev_page)
        
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(self._next_page)
        
        self.page_label = QLabel("Page:")
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._go_to_page)
        
        self.total_pages_label = QLabel("/ ?")
        
        # Zoom controls
        self.zoom_in_btn = QPushButton("🔍+")
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_out_btn = QPushButton("🔍-")
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        
        toolbar.addWidget(self.prev_btn)
        toolbar.addWidget(self.next_btn)
        toolbar.addWidget(self.page_label)
        toolbar.addWidget(self.page_spin)
        toolbar.addWidget(self.total_pages_label)
        toolbar.addStretch()
        toolbar.addWidget(self.zoom_out_btn)
        toolbar.addWidget(self.zoom_in_btn)
        
        layout.addLayout(toolbar)
        
        # Scroll area for PDF content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        
        # PDF display label
        self.pdf_label = QLabel("Loading Manual...")
        self.pdf_label.setAlignment(Qt.AlignCenter)
        self.pdf_label.setStyleSheet("background-color: white; padding: 20px;")
        self.pdf_label.setScaledContents(False)
        
        scroll.setWidget(self.pdf_label)
        layout.addWidget(scroll)
        
        self.setLayout(layout)
        
        # Load PDF
        self.manual_path = resource_path("assets/Manual.pdf")
        if not os.path.exists(self.manual_path):
             self.manual_path = resource_path("assets/manual.pdf")
        
        print(f"DEBUG: HelpPage PDF path: {self.manual_path}, exists: {os.path.exists(self.manual_path)}")
        self._load_pdf()
    
    def _load_pdf(self):
        """Load PDF document and display first page"""
        if not HAS_PYMUPDF:
            self.pdf_label.setText(
                "<h2>PyMuPDF Not Installed</h2>"
                "<p>Run: <code>pip install PyMuPDF</code></p>"
            )
            return
        
        if not os.path.exists(self.manual_path):
            self.pdf_label.setText(
                "<h2>Manual Not Found</h2>"
                "<p>Manual.pdf should be in <b>assets</b> folder.</p>"
            )
            return
        
        try:
            self.pdf_document = fitz.open(self.manual_path)
            total_pages = len(self.pdf_document)
            self.total_pages_label.setText(f"/ {total_pages}")
            self.page_spin.setMaximum(total_pages)
            self._render_page(0)
        except Exception as e:
            self.pdf_label.setText(f"<h2>Error Loading PDF</h2><p>{str(e)}</p>")
    
    def _render_page(self, page_num):
        """Render specific PDF page as image"""
        if not self.pdf_document:
            return
        
        try:
            page = self.pdf_document[page_num]
            
            # Render page to pixmap with zoom
            mat = fitz.Matrix(self.zoom_level, self.zoom_level)
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to QImage
            img_data = pix.samples
            qimage = QImage(
                img_data,
                pix.width,
                pix.height,
                pix.stride,
                QImage.Format_RGB888
            )
            
            # Display in label
            pixmap = QPixmap.fromImage(qimage)
            self.pdf_label.setPixmap(pixmap)
            self.pdf_label.resize(pixmap.size())
            
            self.current_page = page_num
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(page_num + 1)
            self.page_spin.blockSignals(False)
            
            # Update button states
            self.prev_btn.setEnabled(page_num > 0)
            self.next_btn.setEnabled(page_num < len(self.pdf_document) - 1)
            
        except Exception as e:
            self.pdf_label.setText(f"<h2>Error Rendering Page</h2><p>{str(e)}</p>")
    
    def _prev_page(self):
        """Go to previous page"""
        if self.current_page > 0:
            self._render_page(self.current_page - 1)
    
    def _next_page(self):
        """Go to next page"""
        if self.pdf_document and self.current_page < len(self.pdf_document) - 1:
            self._render_page(self.current_page + 1)
    
    def _go_to_page(self, page_num):
        """Jump to specific page"""
        if self.pdf_document:
            self._render_page(page_num - 1)
    
    def _zoom_in(self):
        """Increase zoom level"""
        self.zoom_level = min(self.zoom_level + 0.2, 3.0)
        self._render_page(self.current_page)
    
    def _zoom_out(self):
        """Decrease zoom level"""
        self.zoom_level = max(self.zoom_level - 0.2, 0.5)
        self._render_page(self.current_page)
