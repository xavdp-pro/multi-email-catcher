#!/usr/bin/env python3
"""
GUI — multi-email-catcher
Cross-platform (Linux / Windows) — requires PySide6
  pip install PySide6
"""
import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QFileDialog, QMessageBox,
    QGroupBox, QLabel,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment
from PySide6.QtGui import QFont, QTextCursor, QColor


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
