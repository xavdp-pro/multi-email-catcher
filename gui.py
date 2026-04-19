#!/usr/bin/env python3
"""
GUI Qt locale — multi-email-catcher (source: Google Sheets).
Seule interface graphique du projet (lancer sur une machine avec affichage).

Panneau gauche :
  - Stats live (total / à traiter / déjà fait)
  - Limite de test (spinbox : 0 = tous)
  - Boutons Lancer / Arrêter
Panneau droit :
  - Logs en temps réel

Lancement :
  python gui.py
"""
import os
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTextEdit, QLabel,
    QSpinBox, QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor, QColor


# ── Palette ───────────────────────────────────────────────────────────────────
BG_LOG  = "#1e1e1e"
FG_LOG  = "#d4d4d4"
FG_OK   = "#4ec9b0"
FG_ERR  = "#f44747"
FG_WARN = "#ce9178"
FG_INFO = "#569cd6"


# ── Stats worker (évite de bloquer l'UI) ──────────────────────────────────────
class StatsWorker(QThread):
    """Lit le Google Sheet et compte les lignes avec/sans email."""
    done   = Signal(int, int, int)   # total, todo, already
    failed = Signal(str)

    def run(self):
        try:
            from dotenv import load_dotenv
            import gspread

            load_dotenv(".env")
            sa_file  = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
            sheet_id = os.getenv("SHEET_ID")
            onglet   = os.getenv("SHEET_ONGLET", "BODACC")
            if not sheet_id:
                self.failed.emit("SHEET_ID manquant dans .env")
                return

            gc = gspread.service_account(filename=sa_file)
            ws = gc.open_by_key(sheet_id).worksheet(onglet)
            rows = ws.get_all_records()

            total   = len(rows)
            already = 0
            todo    = 0
            for row in rows:
                name = str(
                    row.get("Société")
                    or row.get("Societe")
                    or row.get("Dénomination")
                    or row.get("Denomination")
                    or ""
                ).strip()
                if not name:
                    continue
                existing = str(row.get("Email") or "").strip()
                if existing:
                    already += 1
                else:
                    todo += 1
            self.done.emit(total, todo, already)
        except Exception as e:
            self.failed.emit(str(e))


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("multi-email-catcher — Google Sheets")
        self.resize(1050, 660)
        self._process: QProcess | None = None
        self._stats_worker: StatsWorker | None = None
        self._setup_ui()
        self._refresh_stats()   # async load au démarrage

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
        left.setMaximumWidth(340)
        lyt = QVBoxLayout(left)
        lyt.setSpacing(10)
        lyt.setContentsMargins(8, 8, 8, 8)

        # --- Stats box
        stats_box = QGroupBox("État du Google Sheet")
        sb = QVBoxLayout(stats_box)
        sb.setSpacing(4)

        self.lbl_total   = QLabel("📊  Total :            —")
        self.lbl_todo    = QLabel("🎯  À traiter :        —")
        self.lbl_already = QLabel("✅  Déjà fait :        —")
        for lbl in (self.lbl_total, self.lbl_todo, self.lbl_already):
            lbl.setStyleSheet("font-family: monospace; font-size: 12px;")
            sb.addWidget(lbl)

        self.btn_refresh = QPushButton("🔄  Rafraîchir")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.clicked.connect(self._refresh_stats)
        sb.addWidget(self.btn_refresh)
        lyt.addWidget(stats_box)

        # --- Options box
        opts_box = QGroupBox("Options")
        form = QFormLayout(opts_box)
        form.setSpacing(6)

        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(0, 100000)
        self.spin_limit.setValue(3)      # par défaut : test rapide
        self.spin_limit.setToolTip(
            "Nombre maximum d'entreprises à traiter avant arrêt.\n"
            "Utile pour tester rapidement sans consommer tout le sheet."
        )
        limit_row = QHBoxLayout()
        limit_row.setSpacing(6)
        limit_row.addWidget(self.spin_limit, 1)
        hint = QLabel("(0 = tous)")
        hint.setStyleSheet("color:#888; font-size:11px;")
        limit_row.addWidget(hint)
        form.addRow("Limite :", limit_row)
        lyt.addWidget(opts_box)

        # --- Buttons
        self.btn_start = QPushButton("▶  Lancer")
        self.btn_start.setMinimumHeight(46)
        self.btn_start.setStyleSheet(
            "font-weight: bold; font-size: 15px;"
            "background: #0e7a0d; color: white; border-radius: 6px;"
        )
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("■  Arrêter")
        self.btn_stop.setMinimumHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "font-size: 13px; color: white;"
            "background: #8b0000; border-radius: 6px;"
        )
        self.btn_stop.clicked.connect(self._stop)

        lyt.addWidget(self.btn_start)
        lyt.addWidget(self.btn_stop)

        self.status_label = QLabel("Prêt")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        lyt.addWidget(self.status_label)

        lyt.addStretch()
        splitter.addWidget(left)

        # ── RIGHT panel (logs) ───────────────────────────────────────────────
        right = QWidget()
        rlyt = QVBoxLayout(right)
        rlyt.setContentsMargins(8, 8, 8, 8)
        rlyt.setSpacing(4)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Logs"))
        hdr.addStretch()
        btn_clear = QPushButton("Effacer")
        btn_clear.setFixedWidth(72)
        btn_clear.clicked.connect(lambda: self.log_area.clear())
        hdr.addWidget(btn_clear)
        rlyt.addLayout(hdr)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Monospace", 9))
        self.log_area.setStyleSheet(f"background:{BG_LOG}; color:{FG_LOG};")
        rlyt.addWidget(self.log_area)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    # ── Stats ─────────────────────────────────────────────────────────────────
    def _refresh_stats(self):
        if self._stats_worker and self._stats_worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.lbl_total.setText("📊  Total :            …")
        self.lbl_todo.setText("🎯  À traiter :        …")
        self.lbl_already.setText("✅  Déjà fait :        …")

        self._stats_worker = StatsWorker()
        self._stats_worker.done.connect(self._on_stats_done)
        self._stats_worker.failed.connect(self._on_stats_failed)
        self._stats_worker.start()

    def _on_stats_done(self, total: int, todo: int, already: int):
        self.lbl_total.setText(f"📊  Total :            {total}")
        self.lbl_todo.setText(f"🎯  À traiter :        {todo}")
        self.lbl_already.setText(f"✅  Déjà fait :        {already}")
        self.btn_refresh.setEnabled(True)
        # Ajuste la borne du spinbox pour qu'on ne demande pas plus que possible
        self.spin_limit.setRange(0, max(todo, 1))

    def _on_stats_failed(self, err: str):
        self.lbl_total.setText("📊  Total :            ❌")
        self.lbl_todo.setText("🎯  À traiter :        ❌")
        self.lbl_already.setText(f"⚠ {err[:40]}")
        self.btn_refresh.setEnabled(True)

    # ── Process control ───────────────────────────────────────────────────────
    def _start(self):
        limit = self.spin_limit.value()
        env = QProcessEnvironment.systemEnvironment()
        env.insert("MAX_COMPANIES", str(limit))

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.setProcessEnvironment(env)
        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.start(sys.executable, ["agent.py"])

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        lim_txt = f"{limit} entreprise(s)" if limit else "toutes les entreprises"
        self.status_label.setText(f"⏳  En cours… ({lim_txt})")
        self._log(f"=== Démarrage — limite : {limit or '∞'} ===\n", FG_OK)

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
            if "📧" in line or "✅" in line or "terminé" in lo:
                self._log(line, FG_OK)
            elif "❌" in line or "error" in lo or "erreur" in lo or "failed" in lo:
                self._log(line, FG_ERR)
            elif "⚠" in line or "warn" in lo or "skip" in lo or "🔒" in line:
                self._log(line, FG_WARN)
            elif line.startswith("  -> ") or "📊" in line:
                self._log(line, FG_INFO)
            else:
                self._log(line)

    def _on_finished(self, exit_code: int, _):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        ok = exit_code == 0
        self._log(f"\n=== Terminé — code {exit_code} ===\n", FG_OK if ok else FG_ERR)
        self.status_label.setText("✅  Terminé" if ok else f"❌  Erreur ({exit_code})")
        self._refresh_stats()

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
    # Garantit que le cwd est bien celui du projet (pour agent.py et .env)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
