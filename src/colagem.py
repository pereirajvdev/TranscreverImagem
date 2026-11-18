"""Janela da colagem especial (Ctrl+Shift+V)."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from icones import criar_icone
from planilha import analisar_planilha, plural


# ============================================================
# JANELA
# ============================================================

class DialogoColagemEspecial(QDialog):
    """Lista as formas especiais de colar. Hoje: Paste from Sheet."""

    PASTE_FROM_SHEET = "paste_from_sheet"

    def __init__(self, texto: str, paleta, parent=None):
        super().__init__(parent)

        self.opcao_escolhida = None
        self.planilha = analisar_planilha(texto)
        self.colunas = self.planilha.colunas

        self.setWindowTitle("Colagem especial")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlag(
            Qt.WindowType.WindowContextHelpButtonHint, False
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        titulo = QLabel("Colagem especial")
        titulo.setObjectName("tituloDialogo")

        subtitulo = QLabel(
            "Escolha como colar o conteúdo da área de transferência."
        )
        subtitulo.setObjectName("descricaoOpcao")
        subtitulo.setWordWrap(True)

        self.botao_planilha = QPushButton("Paste from Sheet")
        self.botao_planilha.setObjectName("opcaoPasteFromSheet")
        self.botao_planilha.setProperty("papel", "opcao")
        self.botao_planilha.setIcon(criar_icone("planilha", paleta.texto))
        self.botao_planilha.setIconSize(QSize(20, 20))
        self.botao_planilha.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_planilha.setEnabled(bool(self.colunas))
        self.botao_planilha.setDefault(True)
        self.botao_planilha.clicked.connect(
            lambda: self._escolher(self.PASTE_FROM_SHEET)
        )

        self.resumo = QLabel(self._texto_resumo())
        self.resumo.setObjectName("descricaoOpcao")
        self.resumo.setWordWrap(True)

        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setAutoDefault(False)
        self.botao_cancelar.clicked.connect(self.reject)

        rodape = QHBoxLayout()
        rodape.addStretch()
        rodape.addWidget(self.botao_cancelar)

        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(4)
        layout.addWidget(self.botao_planilha)
        layout.addWidget(self.resumo)
        layout.addSpacing(6)
        layout.addLayout(rodape)

        (
            self.botao_planilha
            if self.colunas
            else self.botao_cancelar
        ).setFocus()

    def _texto_resumo(self) -> str:
        if not self.colunas:
            return (
                "A área de transferência não tem dados tabulares "
                "para colar."
            )

        n = len(self.colunas)
        colunas = plural(n, "coluna", "colunas")
        linhas = plural(self.planilha.linhas, "linha", "linhas")
        notas = plural(n, "nota", "notas")

        return (
            f"{colunas} e {linhas} detectadas. "
            f"Será criada {notas}, uma por coluna."
            if n == 1
            else f"{colunas} e {linhas} detectadas. "
            f"Serão criadas {notas}, uma por coluna."
        )

    def _escolher(self, opcao: str):
        self.opcao_escolhida = opcao
        self.accept()
