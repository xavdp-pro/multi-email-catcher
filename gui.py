#!/usr/bin/env python3
"""
GUI — multi-email-catcher  (source: Google Sheets)
Panneau gauche : bouton Lancer + statut
Panneau droit  : logs en temps réel

Lancement :
  python gui.py
"""
import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTextEdit, QLabel,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment
from PySide6.QtGui import QFont, QTextCursor, QColor


# ── Palette ───────────────────────────────────────────────────────────────────
BG_LOG   = "#1e1e1e"
FG_LOG   = "#d4d4d4"
FG_OK    = "#4ec9b0"
FG_ERR   = "#f44747"
FG_WARN  = "#ce9178"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("multi-email-catcher — Google Sheets")
        self.resize(1000, 640)
        self._process: QProcess | None = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main.addWidget(splitter)

        # ── LEFT panel ───────────────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(8, 8, 8, 8)

        self.btn_start = QPushButton("▶  Lancer")
        self.btn_start.setMinimumHeight(48)
        self.btn_start.setStyleSheet(
            "font-weight: bold; font-size: 15px;"
            "background: #0e7a0d; color: white; border-radius: 6px;"
        )
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("■  Arrêter")
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "font-size: 13px; color: white;"
            "background: #8b0000; border-radius: 6px;"
        )
        self.btn_stop.clicked.connect(self._stop)

        self.status_label = QLabel("Prêt")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")

        left_layout.addStretch()
        left_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_stop)
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        splitter.addWidget(left)

        # ── RIGHT panel (logs) ────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Logs"))
        log_header.addStretch()
        btn_clear = QPushButton("Effacer")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(lambda: self.log_area.clear())
        log_header.addWidget(btn_clear)
        right_layout.addLayout(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Monospace", 9))
        self.log_area.setStyleSheet(f"background:{BG_LOG}; color:{FG_LOG};")
        right_layout.addWidget(self.log_area)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    # ── Process control ───────────────────────────────────────────────────────
    def _start(self):
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.start(sys.executable, ["agent.py"])

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("⏳  En cours…")
        self._log("=== Démarrage ===\n", FG_OK)

    def _stop(self):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.terminate()
            self._log("\n=== Arrêté par l'utilisateur ===\n", FG_WARN)

    # ── Output ────────────────────────────────────────────────────────────────
    def _on_output(self):
        raw  = bytes(self._process.readAllStandardOutput())
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines(keepends=True):
            lo = line.lower()
            if any(k in lo for k in ("✅", "📧", "ok", "found", "terminé")):
                self._log(line, FG_OK)
            elif any(k in lo for k in ("❌", "error", "erreur", "failed")):
                self._log(line, FG_ERR)
            elif any(k in lo for k in ("⚠️", "warn", "skip")):
                self._log(line, FG_WARN)
            else:
                self._log(line)

    def _on_finished(self, exit_code: int, _):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        ok = exit_code == 0
        self._log(f"\n=== Terminé — code {exit_code} ===\n", FG_OK if ok else FG_ERR)
        self.status_label.setText("✅  Terminé" if ok else f"❌  Erreur ({exit_code})")

    # ── Log helper ────────────────────────────────────────────────────────────
    def _log(self, text: str, color: str | None = None):
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color or FG_LOG))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.log_area.setTextCursor(cursor)
        self.log_area.ensureCursorVisible()

    def closeEvent(self, event):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

import sys
import os
from dotenv import dotenv_values
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLineEdit, QTextEdit,
    QGroupBox, QLabel, QFormLayout,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment
from PySide6.QtGui import QFont, QTextCursor, QColor


# ── Palette ───────────────────────────────────────────────────────────────────
BG_LOG   = "#1e1e1e"
FG_LOG   = "#d4d4d4"
FG_OK    = "#4ec9b0"
FG_ERR   = "#f44747"
FG_WARN  = "#ce9178"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("multi-email-catcher — Google Sheets")
        self.resize(1100, 680)
        self._process: QProcess | None = None
        self._setup_ui()
        self._load_env()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main.addWidget(splitter)

        # ── LEFT panel ───────────────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(280)
        left.setMaximumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(8, 8, 8, 8)

        # Google Sheets params
        sheet_box = QGroupBox("Google Sheets")
        form = QFormLayout(sheet_box)
        form.setSpacing(8)

        self.sheet_id    = QLineEdit()
        self.sheet_id.setPlaceholderText("1aYG...M5nk")
        self.sheet_onglet = QLineEdit()
        self.sheet_onglet.setPlaceholderText("BODACC")
        self.sheet_onglet.setText("BODACC")
        self.sa_file     = QLineEdit()
        self.sa_file.setPlaceholderText("gbsproject-xxx.json")

        form.addRow("Sheet ID :", self.sheet_id)
        form.addRow("Onglet :",   self.sheet_onglet)
        form.addRow("Clé JSON :", self.sa_file)
        left_layout.addWidget(sheet_box)

        # Groq
        groq_box = QGroupBox("Groq API")
        groq_form = QFormLayout(groq_box)
        self.groq_key = QLineEdit()
        self.groq_key.setPlaceholderText("gsk_…")
        self.groq_key.setEchoMode(QLineEdit.Password)
        groq_form.addRow("API Key :", self.groq_key)
        left_layout.addWidget(groq_box)

        # Buttons
        self.btn_start = QPushButton("▶  Lancer")
        self.btn_start.setMinimumHeight(42)
        self.btn_start.setStyleSheet(
            "font-weight: bold; font-size: 14px;"
            "background: #0e7a0d; color: white; border-radius: 5px;"
        )
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("■  Arrêter")
        self.btn_stop.setMinimumHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "font-size: 13px; color: white;"
            "background: #8b0000; border-radius: 5px;"
        )
        self.btn_stop.clicked.connect(self._stop)

        left_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_stop)

        self.status_label = QLabel("Prêt")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        left_layout.addWidget(self.status_label)

        left_layout.addStretch()
        splitter.addWidget(left)

        # ── RIGHT panel (logs) ────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Logs"))
        log_header.addStretch()
        btn_clear = QPushButton("Effacer")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(lambda: self.log_area.clear())
        log_header.addWidget(btn_clear)
        right_layout.addLayout(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Monospace", 9))
        self.log_area.setStyleSheet(f"background:{BG_LOG}; color:{FG_LOG};")
        right_layout.addWidget(self.log_area)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    # ── Load .env into fields ─────────────────────────────────────────────────
    def _load_env(self):
        env = dotenv_values(".env")
        if env.get("SHEET_ID"):
            self.sheet_id.setText(env["SHEET_ID"])
        if env.get("SHEET_ONGLET"):
            self.sheet_onglet.setText(env["SHEET_ONGLET"])
        if env.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
            self.sa_file.setText(env["GOOGLE_SERVICE_ACCOUNT_FILE"])
        if env.get("GROQ_API_KEY"):
            self.groq_key.setText(env["GROQ_API_KEY"])

    # ── Process control ───────────────────────────────────────────────────────
    def _start(self):
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("SHEET_ID",                    self.sheet_id.text().strip())
        env.insert("SHEET_ONGLET",                self.sheet_onglet.text().strip() or "BODACC")
        env.insert("GOOGLE_SERVICE_ACCOUNT_FILE", self.sa_file.text().strip())
        env.insert("GROQ_API_KEY",                self.groq_key.text().strip())
        self._process.setProcessEnvironment(env)

        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.start(sys.executable, ["agent.py"])

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("⏳  En cours…")
        self._log("=== Démarrage ===\n", FG_OK)

    def _stop(self):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.terminate()
            self._log("\n=== Arrêté par l'utilisateur ===\n", FG_WARN)

    # ── Output ────────────────────────────────────────────────────────────────
    def _on_output(self):
        raw  = bytes(self._process.readAllStandardOutput())
        text = raw.decode("utf-8", errors="replace")
        # Basic coloring
        for line in text.splitlines(keepends=True):
            lo = line.lower()
            if any(k in lo for k in ("✅", "📧", "ok", "found")):
                self._log(line, FG_OK)
            elif any(k in lo for k in ("❌", "error", "erreur", "failed")):
                self._log(line, FG_ERR)
            elif any(k in lo for k in ("⚠️", "warn", "skip")):
                self._log(line, FG_WARN)
            else:
                self._log(line)

    def _on_finished(self, exit_code: int, _):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        ok = exit_code == 0
        self._log(f"\n=== Terminé — code {exit_code} ===\n", FG_OK if ok else FG_ERR)
        self.status_label.setText("✅  Terminé" if ok else f"❌  Erreur ({exit_code})")

    # ── Log helper ────────────────────────────────────────────────────────────
    def _log(self, text: str, color: str | None = None):
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color or FG_LOG))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.log_area.setTextCursor(cursor)
        self.log_area.ensureCursorVisible()

    def closeEvent(self, event):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("multi-email-catcher")
        self.resize(960, 680)
        self._process: QProcess | None = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Input CSV
        in_box = QGroupBox("Fichier d'entrée  (TSV : nom TAB siren)")
        in_row = QHBoxLayout(in_box)
        self.input_path = QLineEdit("input/companies.csv")
        btn_in = QPushButton("Parcourir…")
        btn_in.setFixedWidth(110)
        btn_in.clicked.connect(self._browse_input)
        in_row.addWidget(self.input_path)
        in_row.addWidget(btn_in)
        layout.addWidget(in_box)

        # Output CSV
        out_box = QGroupBox("Fichier de sortie")
        out_row = QHBoxLayout(out_box)
        self.output_path = QLineEdit("output/results.csv")
        btn_out = QPushButton("Parcourir…")
        btn_out.setFixedWidth(110)
        btn_out.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_path)
        out_row.addWidget(btn_out)
        layout.addWidget(out_box)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶  Lancer")
        self.btn_start.setMinimumHeight(38)
        self.btn_start.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("■  Arrêter")
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("color: #c00;")
        self.btn_stop.clicked.connect(self._stop)

        btn_clear = QPushButton("Effacer logs")
        btn_clear.clicked.connect(self.log_area.clear if hasattr(self, "log_area") else lambda: None)

        self.status_label = QLabel("Prêt")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addSpacing(12)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(self.status_label)
        layout.addLayout(btn_row)

        # Logs
        log_box = QGroupBox("Logs")
        log_layout = QVBoxLayout(log_box)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Monospace", 9))
        self.log_area.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        log_layout.addWidget(self.log_area)
        layout.addWidget(log_box, stretch=1)

        # Wire clear button after log_area exists
        btn_clear.clicked.disconnect()
        btn_clear.clicked.connect(self.log_area.clear)

    # ── File pickers ──────────────────────────────────────────────────────────
    def _browse_input(self):
        start = self.input_path.text() or "."
        path, _ = QFileDialog.getOpenFileName(
            self, "Fichier CSV d'entrée", start,
            "CSV / TSV (*.csv *.tsv);;Tous (*.*)"
        )
        if path:
            self.input_path.setText(path)

    def _browse_output(self):
        start = self.output_path.text() or "output/results.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Fichier CSV de sortie", start,
            "CSV (*.csv);;Tous (*.*)"
        )
        if path:
            self.output_path.setText(path)

    # ── Process control ───────────────────────────────────────────────────────
    def _start(self):
        input_file = self.input_path.text().strip()
        if not os.path.exists(input_file):
            QMessageBox.warning(self, "Fichier introuvable",
                                f"Le fichier d'entrée n'existe pas :\n{input_file}")
            return

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("INPUT_CSV", input_file)
        env.insert("OUTPUT_CSV", self.output_path.text().strip())
        self._process.setProcessEnvironment(env)

        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)

        # Use same Python interpreter that launched this GUI
        self._process.start(sys.executable, ["agent.py"])

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("⏳  En cours…")
        self._log("=== Démarrage ===\n", "#4ec9b0")

    def _stop(self):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.terminate()
            self._log("\n=== Arrêté par l'utilisateur ===\n", "#ce9178")

    # ── Process output ────────────────────────────────────────────────────────
    def _on_output(self):
        raw = bytes(self._process.readAllStandardOutput())
        text = raw.decode("utf-8", errors="replace")
        self._log(text)

    def _on_finished(self, exit_code: int, _exit_status):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        ok = exit_code == 0
        color = "#4ec9b0" if ok else "#f44747"
        self._log(f"\n=== Terminé — code {exit_code} ===\n", color)
        self.status_label.setText(
            f"✅  Terminé" if ok else f"❌  Erreur (code {exit_code})"
        )

    # ── Log helper ────────────────────────────────────────────────────────────
    def _log(self, text: str, color: str | None = None):
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        if color:
            fmt.setForeground(QColor(color))
        else:
            fmt.setForeground(QColor("#d4d4d4"))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.log_area.setTextCursor(cursor)
        self.log_area.ensureCursorVisible()

    # ── Close ─────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
