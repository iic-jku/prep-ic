# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Qt binding: PySide6, PyQt6 as fallback. All GUI modules import Qt from here."""

try:
    from PySide6.QtCore import QEvent, QLocale, QPointF, QRect, QRectF, QSize, Qt, QTimer
    from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QFontDatabase, QIcon, QImage,
                               QKeySequence, QPainter, QPalette, QPen, QTextCursor, QTextFormat, QTransform)
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                   QDoubleSpinBox, QFileDialog, QFrame, QGraphicsItem, QGraphicsRectItem,
                                   QGraphicsScene,
                                   QGraphicsSimpleTextItem, QGraphicsView, QGridLayout, QGroupBox,
                                   QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                                   QPlainTextEdit, QScrollArea, QStackedWidget, QStyledItemDelegate,
                                   QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                   QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)
    QT_API = "PySide6"
except ImportError as pyside_error:  # pragma: no cover
    try:
        from PyQt6.QtCore import QEvent, QLocale, QPointF, QRect, QRectF, QSize, Qt, QTimer
        from PyQt6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QFontDatabase, QIcon, QImage,
                                 QKeySequence, QPainter, QPalette, QPen, QTextCursor, QTextFormat, QTransform)
        from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                                     QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame, QGraphicsItem,
                                     QGraphicsRectItem,
                                     QGraphicsScene,
                                     QGraphicsSimpleTextItem, QGraphicsView, QGridLayout, QGroupBox,
                                     QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                                     QPlainTextEdit, QScrollArea, QStackedWidget, QStyledItemDelegate,
                                     QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                     QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)
        QT_API = "PyQt6"
    except ImportError:
        if isinstance(pyside_error, ModuleNotFoundError) and str(pyside_error.name).split(".")[0] == "PySide6":
            raise ImportError("Qt is missing. Install it with:  pip install PySide6-Essentials") from None
        raise ImportError(f"PySide6 cannot be loaded: {pyside_error}") from None  # installed, a library it needs is not
