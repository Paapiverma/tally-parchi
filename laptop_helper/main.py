"""
main.py – PyQt6 GUI for the Tally Parchi Laptop Helper.

Tabs:
  1. Pending Parchis  – list + [Send to Tally] + [Void]
  2. Sent to Tally    – history + unfinished-voucher monitor
  3. Master Sync      – pull from Tally → push to Supabase
  4. Settings         – Tally connection indicator
"""
import os
import sys
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QHeaderView, QFrame, QSizePolicy, QSplitter, QProgressBar,
)

import supabase_client as db
import tally_client as tally
import posting_engine as engine
from config import config


# ─── Colours & fonts ─────────────────────────────────────────────────────────
COLORS = {
    "PENDING":      "#f59e0b",   # amber
    "POSTING":      "#3b82f6",   # blue
    "SENT_TO_TALLY":"#10b981",   # green
    "FAILED":       "#ef4444",   # red
    "VOID":         "#9ca3af",   # grey
}


# ─── Worker threads ──────────────────────────────────────────────────────────

class SendWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)   # ok, reason

    def __init__(self, parchi: dict):
        super().__init__()
        self.parchi = parchi

    def run(self):
        result = engine.send_parchi(
            self.parchi,
            progress_cb=lambda msg: self.progress.emit(msg),
        )
        self.finished.emit(result["ok"], result.get("reason", ""))


class MasterSyncWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        self.progress.emit("Connecting to Tally…")
        conn = tally.check_connection()
        if not conn["ok"]:
            self.finished.emit(False, conn["reason"])
            return

        self.progress.emit(f"Connected: {conn['company']}\nFetching masters…")
        masters = tally.sync_masters()

        parties = len(masters.get("parties", []))
        items   = len(masters.get("items", []))
        self.progress.emit(f"Found {parties} parties, {items} stock items.\nPushing to Supabase…")

        ok = db.upsert_masters(masters)
        if ok:
            self.finished.emit(True, f"Sync complete.\n{parties} parties · {items} items · {len(masters.get('units', []))} units")
        else:
            self.finished.emit(False, "Supabase write failed. Check connection.")


# ─── Login dialog ─────────────────────────────────────────────────────────────

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tally Parchi – Login")
        self.setFixedWidth(360)
        layout = QFormLayout(self)

        self.email_input = QLineEdit(config.APP_EMAIL)
        self.pwd_input   = QLineEdit(config.APP_PASSWORD)
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addRow("Email:", self.email_input)
        layout.addRow("Password:", self.pwd_input)

        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self._do_login)
        btn_layout.addWidget(self.login_btn)
        layout.addRow(btn_layout)

        self.status_label = QLabel("")
        layout.addRow(self.status_label)

    def _do_login(self):
        self.login_btn.setEnabled(False)
        self.status_label.setText("Logging in…")
        result = db.login(self.email_input.text(), self.pwd_input.text())
        if result["ok"]:
            self.accept()
        else:
            self.status_label.setText(f"✗ {result['reason']}")
            self.login_btn.setEnabled(True)


# ─── Pending tab ──────────────────────────────────────────────────────────────

class PendingTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list[SendWorker] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("⟳  Refresh")
        self.refresh_btn.clicked.connect(self.load_parchis)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addStretch()
        self.tally_status = QLabel("Tally: checking…")
        toolbar.addWidget(self.tally_status)
        layout.addLayout(toolbar)

        # Splitter: table on top, log below
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Parchi ID", "Party", "Date", "Items", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_change)
        splitter.addWidget(self.table)

        # Detail + log panel
        detail_frame = QFrame()
        detail_layout = QVBoxLayout(detail_frame)

        btn_row = QHBoxLayout()
        self.send_btn = QPushButton("▶  Send to Tally")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_selected)
        self.void_btn = QPushButton("✕  Void")
        self.void_btn.setEnabled(False)
        self.void_btn.clicked.connect(self._void_selected)
        self.photo_btn = QPushButton("📷  View Face Photo")
        self.photo_btn.setEnabled(False)
        self.photo_btn.clicked.connect(self._view_photo_selected)
        btn_row.addWidget(self.send_btn)
        btn_row.addWidget(self.void_btn)
        btn_row.addWidget(self.photo_btn)
        btn_row.addStretch()
        detail_layout.addLayout(btn_row)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        self.log_box.setPlaceholderText("Progress log appears here…")
        detail_layout.addWidget(self.log_box)

        splitter.addWidget(detail_frame)
        splitter.setSizes([320, 180])
        layout.addWidget(splitter)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}]  {msg}")

    def check_tally(self):
        result = tally.check_connection()
        if result["ok"]:
            self.tally_status.setText(f"✓ Tally: {result['company']}")
            self.tally_status.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.tally_status.setText("✗ Tally offline")
            self.tally_status.setStyleSheet("color: #ef4444; font-weight: bold;")

    def load_parchis(self):
        self.table.setRowCount(0)
        self._current_parchis = db.get_pending_parchis()
        for row_idx, p in enumerate(self._current_parchis):
            self.table.insertRow(row_idx)
            item_count = len(p.get("parchi_items", []))

            self.table.setItem(row_idx, 0, QTableWidgetItem(p.get("parchi_id", "")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(p.get("party", "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(p.get("date", "")))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{item_count} item{'s' if item_count != 1 else ''}"))

            status_item = QTableWidgetItem(p.get("status", ""))
            color = COLORS.get(p.get("status", ""), "#ffffff")
            status_item.setForeground(QColor(color))
            self.table.setItem(row_idx, 4, status_item)

        self._current_parchis_map = {p["parchi_id"]: p for p in self._current_parchis}

    def _selected_parchi(self) -> dict | None:
        rows = self.table.selectedItems()
        if not rows:
            return None
        pid = self.table.item(self.table.currentRow(), 0).text()
        return self._current_parchis_map.get(pid)

    def _on_selection_change(self):
        p = self._selected_parchi()
        enabled = p is not None and p.get("status") == "PENDING"
        self.send_btn.setEnabled(enabled)
        self.void_btn.setEnabled(enabled)
        has_photo = p is not None and bool(p.get("photo_url"))
        self.photo_btn.setEnabled(has_photo)

    def _view_photo_selected(self):
        import base64
        from PyQt6.QtGui import QPixmap, QImage
        p = self._selected_parchi()
        if not p or not p.get("photo_url"):
            return

        raw_b64 = p["photo_url"].split(",")[-1]
        try:
            img_data = base64.b64decode(raw_b64)
            image = QImage()
            image.loadFromData(img_data)
            pixmap = QPixmap.fromImage(image)

            dlg = QDialog(self)
            dlg.setWindowTitle(f"Customer Face Photo - {p['parchi_id']}")
            d_layout = QVBoxLayout(dlg)

            info_lbl = QLabel(f"Party: {p.get('party')}   |   Date: {p.get('date')}")
            info_lbl.setStyleSheet("font-weight: bold; margin-bottom: 8px;")
            d_layout.addWidget(info_lbl)

            lbl = QLabel()
            lbl.setPixmap(pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            d_layout.addWidget(lbl)

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.accept)
            d_layout.addWidget(close_btn)

            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to display image: {e}")

    def _send_selected(self):
        p = self._selected_parchi()
        if not p:
            return
        self.send_btn.setEnabled(False)
        self.void_btn.setEnabled(False)
        self._log(f"Starting send: {p['parchi_id']}")

        worker = SendWorker(p)
        worker.progress.connect(self._log)
        worker.finished.connect(self._on_send_done)
        self._workers.append(worker)
        worker.start()

    def _on_send_done(self, ok: bool, reason: str):
        if ok:
            self._log("✓ Done.")
        else:
            QMessageBox.warning(self, "Send Failed", reason)
        self.load_parchis()

    def _void_selected(self):
        p = self._selected_parchi()
        if not p:
            return
        reply = QMessageBox.question(
            self, "Void Parchi",
            f"Void parchi {p['parchi_id']}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            db.void_parchi(p["parchi_id"])
            self._log(f"Voided: {p['parchi_id']}")
            self.load_parchis()


# ─── Sent tab ─────────────────────────────────────────────────────────────────

class SentTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.clicked.connect(self.load_sent)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Parchi ID", "Party", "Date", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # Unfinished monitor section
        monitor_label = QLabel("Unfinished in Tally (rates not yet entered):")
        monitor_label.setStyleSheet("font-weight: bold; margin-top: 12px;")
        layout.addWidget(monitor_label)

        self.monitor_box = QTextEdit()
        self.monitor_box.setReadOnly(True)
        self.monitor_box.setMaximumHeight(120)
        self.monitor_box.setPlaceholderText("Click Refresh to check Tally for unfinished vouchers…")
        layout.addWidget(self.monitor_box)

    def load_sent(self):
        self.table.setRowCount(0)
        parchis = db.get_sent_parchis()
        for row_idx, p in enumerate(parchis):
            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(p.get("parchi_id", "")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(p.get("party", "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(p.get("date", "")))
            status_item = QTableWidgetItem("SENT_TO_TALLY")
            status_item.setForeground(QColor(COLORS["SENT_TO_TALLY"]))
            self.table.setItem(row_idx, 3, status_item)

        # Unfinished monitor (placeholder – real implementation queries Tally amount)
        self.monitor_box.setPlaceholderText(
            "Full unfinished-voucher check requires querying Tally amount field.\n"
            "This is the placeholder for that feature."
        )


# ─── Master sync tab ─────────────────────────────────────────────────────────

class MasterSyncTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: MasterSyncWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel(
            "Pull party ledgers, stock items, and units from Tally\n"
            "and push them to Supabase for the phone app dropdowns."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.sync_btn = QPushButton("⟳  Sync Masters Now")
        self.sync_btn.setFixedHeight(40)
        self.sync_btn.clicked.connect(self._start_sync)
        layout.addWidget(self.sync_btn)

        self.last_sync_label = QLabel("Last sync: never")
        layout.addWidget(self.last_sync_label)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Sync log appears here…")
        layout.addWidget(self.log_box)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}]  {msg}")

    def _start_sync(self):
        self.sync_btn.setEnabled(False)
        self._log("Starting master sync…")
        self._worker = MasterSyncWorker()
        self._worker.progress.connect(self._log)
        self._worker.finished.connect(self._on_sync_done)
        self._worker.start()

    def _on_sync_done(self, ok: bool, msg: str):
        self._log(msg)
        self.sync_btn.setEnabled(True)
        if ok:
            self.last_sync_label.setText(f"Last sync: {datetime.now().strftime('%d %b %Y  %H:%M')}")
        else:
            QMessageBox.warning(self, "Sync Failed", msg)


# ─── Settings tab ────────────────────────────────────────────────────────────

class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)

        layout.addRow("Tally Host:", QLabel(config.TALLY_HOST))
        layout.addRow("Tally Port:", QLabel(str(config.TALLY_PORT)))
        layout.addRow("Expected Company:", QLabel(config.TALLY_COMPANY or "(not set)"))
        layout.addRow("Supabase URL:", QLabel(config.SUPABASE_URL[:40] + "…" if len(config.SUPABASE_URL) > 40 else config.SUPABASE_URL))

        self.test_btn = QPushButton("Test Tally Connection")
        self.test_btn.clicked.connect(self._test_tally)
        layout.addRow(self.test_btn)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addRow(self.result_label)

    def _test_tally(self):
        self.result_label.setText("Checking…")
        result = tally.check_connection()
        if result["ok"]:
            self.result_label.setText(f"✓ Connected — Company: {result['company']}")
            self.result_label.setStyleSheet("color: #10b981;")
        else:
            self.result_label.setText(f"✗ {result['reason']}")
            self.result_label.setStyleSheet("color: #ef4444;")


# ─── Main window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tally Parchi – Laptop Helper")
        self.setMinimumSize(860, 580)

        # Tabs
        tabs = QTabWidget()
        self.pending_tab  = PendingTab()
        self.sent_tab     = SentTab()
        self.sync_tab     = MasterSyncTab()
        self.settings_tab = SettingsTab()

        tabs.addTab(self.pending_tab,  "📋  Pending Parchis")
        tabs.addTab(self.sent_tab,     "✓  Sent to Tally")
        tabs.addTab(self.sync_tab,     "⟳  Master Sync")
        tabs.addTab(self.settings_tab, "⚙  Settings")

        self.setCentralWidget(tabs)

        # Status bar
        self.statusBar().showMessage("Ready")

        # Auto-refresh every 60 s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60_000)

        # Initial load
        self.pending_tab.load_parchis()

        # Async Tally check (so UI opens instantly)
        threading.Thread(target=self.pending_tab.check_tally, daemon=True).start()

        # Crash recovery
        threading.Thread(target=engine.recover_posting_parchis, daemon=True).start()

    def _auto_refresh(self):
        self.pending_tab.load_parchis()
        threading.Thread(target=self.pending_tab.check_tally, daemon=True).start()


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tallyparchi.laptophelper.v1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if getattr(sys, 'frozen', False):
        basedir = os.path.dirname(sys.executable)
    else:
        basedir = os.path.dirname(os.path.abspath(__file__))
    
    icon_png = os.path.join(basedir, "app_icon.png")
    icon_ico = os.path.join(basedir, "app_icon.ico")
    if os.path.exists(icon_png):
        app.setWindowIcon(QIcon(icon_png))
    elif os.path.exists(icon_ico):
        app.setWindowIcon(QIcon(icon_ico))

    # Dark-ish palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor("#1e1e2e"))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Base,            QColor("#181825"))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor("#1e1e2e"))
    palette.setColor(QPalette.ColorRole.Text,            QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Button,          QColor("#313244"))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor("#89b4fa"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(palette)

    # Login
    login_dlg = LoginDialog()
    if login_dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
