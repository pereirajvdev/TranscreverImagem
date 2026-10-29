
import sys
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TITULO_JANELA = "TranscreverImagem"

PASTA_PROJETO = Path(__file__).resolve().parent.parent
PASTA_TESSERACT = PASTA_PROJETO / "tesseract"
CAMINHO_TESSERACT = PASTA_TESSERACT / "tesseract.exe"

LARGURA_MAXIMA_IMAGEM = 800
ALTURA_MAXIMA_IMAGEM = 600


if CAMINHO_TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(
        CAMINHO_TESSERACT
    )
else:
    CAMINHO_TESSERACT = None


# ============================================================
# TRANSCRITOR OCR
# ============================================================

class TranscritorOCR(QThread):
    concluido = Signal(str)
    erro = Signal(str)

    def __init__(self, imagem: QImage, parent=None):
        super().__init__(parent)
        self.imagem = imagem.copy()

    def run(self):
        try:
            if not CAMINHO_TESSERACT:
                raise RuntimeError(
                    "Tesseract não encontrado.\n\n"
                    "Verifique se o arquivo existe em:\n"
                    f"{PASTA_TESSERACT}\\tesseract.exe"
                )

            buffer = QBuffer()
            buffer.open(
                QIODevice.OpenModeFlag.WriteOnly
            )

            if not self.imagem.save(buffer, "PNG"):
                buffer.close()
                raise RuntimeError(
                    "Não foi possível converter a imagem."
                )

            dados = bytes(buffer.data())
            buffer.close()

            with Image.open(BytesIO(dados)) as imagem:
                imagem = imagem.convert("RGB")

                texto = pytesseract.image_to_string(
                    imagem,
                    lang="por+eng",
                )

            if not texto.strip():
                texto = (
                    "Nenhum texto foi identificado na imagem."
                )

            self.concluido.emit(texto)

        except Exception as exc:
            self.erro.emit(str(exc))


# ============================================================
# EDITOR DE IMAGEM E TEXTO
# ============================================================

class EditorTranscricao(QWidget):
    transcrever_solicitado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.imagem_atual = None

        self.setObjectName("editorTranscricao")

        self.criar_interface()

        self.timer_botao = QTimer(self)
        self.timer_botao.setSingleShot(True)
        self.timer_botao.setInterval(500)
        self.timer_botao.timeout.connect(
            self.botao_transcrever.hide
        )

    def criar_interface(self):
        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(8)

        # Área da imagem
        self.container_imagem = QFrame(self)
        self.container_imagem.setObjectName(
            "containerImagem"
        )
        self.container_imagem.setFrameShape(
            QFrame.Shape.NoFrame
        )
        self.container_imagem.setMouseTracking(True)

        self.area_imagem = QLabel(
            self.container_imagem
        )
        self.area_imagem.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.area_imagem.setMouseTracking(True)

        self.botao_transcrever = QPushButton(
            "Transcrever",
            self.container_imagem,
        )
        self.botao_transcrever.setObjectName(
            "botaoTranscrever"
        )
        self.botao_transcrever.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_transcrever.clicked.connect(
            self.transcrever_solicitado.emit
        )

        self.area_imagem.installEventFilter(self)
        self.botao_transcrever.installEventFilter(self)

        self.botao_transcrever.hide()
        self.container_imagem.hide()

        layout_principal.addWidget(
            self.container_imagem,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        # Área do texto
        self.editor_texto = QTextEdit(self)
        self.editor_texto.setObjectName("editorTexto")
        self.editor_texto.setPlaceholderText(
            "Cole uma imagem ou abra um arquivo para "
            "começar a transcrição..."
        )

        layout_principal.addWidget(
            self.editor_texto,
            stretch=1,
        )

    def definir_imagem(self, imagem: QImage):
        if imagem.isNull():
            return

        self.timer_botao.stop()
        self.imagem_atual = imagem.copy()

        pixmap = QPixmap.fromImage(self.imagem_atual)

        pixmap = pixmap.scaled(
            LARGURA_MAXIMA_IMAGEM,
            ALTURA_MAXIMA_IMAGEM,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.area_imagem.setPixmap(pixmap)
        self.area_imagem.setFixedSize(pixmap.size())

        self.container_imagem.setFixedSize(
            pixmap.size()
        )

        self.area_imagem.move(0, 0)

        self.editor_texto.clear()
        self.editor_texto.hide()

        self.container_imagem.show()
        self.botao_transcrever.hide()

        self.posicionar_botao()

    def posicionar_botao(self):
        self.botao_transcrever.adjustSize()

        margem = 8

        x = max(
            margem,
            self.container_imagem.width()
            - self.botao_transcrever.width()
            - margem,
        )

        self.botao_transcrever.move(x, margem)
        self.botao_transcrever.raise_()

    def eventFilter(self, objeto, evento):
        if objeto in (
            self.area_imagem,
            self.botao_transcrever,
        ):
            if evento.type() == evento.Type.Enter:
                self.timer_botao.stop()

                if self.imagem_atual is not None:
                    self.botao_transcrever.show()
                    self.botao_transcrever.raise_()

            elif evento.type() == evento.Type.Leave:
                self.timer_botao.start()

        return super().eventFilter(objeto, evento)

    def mostrar_texto(self, texto: str):
        self.timer_botao.stop()

        self.container_imagem.hide()
        self.botao_transcrever.hide()

        self.editor_texto.setPlainText(texto)
        self.editor_texto.show()
        self.editor_texto.setFocus()

    def limpar(self):
        self.timer_botao.stop()

        self.imagem_atual = None

        self.container_imagem.hide()
        self.botao_transcrever.hide()

        self.editor_texto.clear()
        self.editor_texto.show()

    def definir_estado_transcricao(
        self,
        em_andamento: bool,
    ):
        self.botao_transcrever.setEnabled(
            not em_andamento
        )

        self.botao_transcrever.setText(
            "Transcrevendo..."
            if em_andamento
            else "Transcrever"
        )


# ============================================================
# JANELA PRINCIPAL
# ============================================================

class JanelaPrincipal(QMainWindow):

    def __init__(self):
        super().__init__()

        self.transcritor = None

        self.setWindowTitle(TITULO_JANELA)
        self.resize(1000, 750)
        self.setMinimumSize(600, 450)

        self.criar_interface()
        self.configurar_atalhos()
        self.aplicar_estilo()

        self.statusBar().showMessage(
            "Pronto para transcrever."
        )

    def criar_interface(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        layout_principal = QVBoxLayout(central)
        layout_principal.setContentsMargins(
            16, 16, 16, 12
        )
        layout_principal.setSpacing(12)

        # Título
        self.titulo = QLabel("Transcrever imagem")
        self.titulo.setObjectName("titulo")

        layout_principal.addWidget(self.titulo)

        # Editor
        self.editor = EditorTranscricao(self)

        self.editor.transcrever_solicitado.connect(
            self.transcrever_imagem
        )

        # Área rolável para imagens maiores
        self.area_rolagem = QScrollArea(self)
        self.area_rolagem.setObjectName("areaRolagem")
        self.area_rolagem.setWidgetResizable(True)
        self.area_rolagem.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.area_rolagem.setWidget(self.editor)

        layout_principal.addWidget(
            self.area_rolagem,
            stretch=1,
        )

        # Botões inferiores
        layout_botoes = QHBoxLayout()
        layout_botoes.setSpacing(8)

        self.botao_abrir = QPushButton("Abrir imagem")
        self.botao_abrir.clicked.connect(
            self.abrir_imagem
        )

        self.botao_colar = QPushButton("Colar imagem")
        self.botao_colar.clicked.connect(
            self.colar_conteudo
        )

        self.botao_copiar = QPushButton("Copiar texto")
        self.botao_copiar.clicked.connect(
            self.copiar_texto
        )
        self.botao_copiar.hide()

        self.botao_nova = QPushButton("Nova imagem")
        self.botao_nova.clicked.connect(
            self.nova_imagem
        )

        layout_botoes.addWidget(self.botao_abrir)
        layout_botoes.addWidget(self.botao_colar)
        layout_botoes.addStretch()
        layout_botoes.addWidget(self.botao_copiar)
        layout_botoes.addWidget(self.botao_nova)

        layout_principal.addLayout(layout_botoes)

    def configurar_atalhos(self):
        self.atalho_abrir = QShortcut(
            QKeySequence("Ctrl+O"),
            self,
        )
        self.atalho_abrir.activated.connect(
            self.abrir_imagem
        )

        self.atalho_colar = QShortcut(
            QKeySequence("Ctrl+V"),
            self,
        )
        self.atalho_colar.activated.connect(
            self.colar_conteudo
        )

        self.atalho_copiar = QShortcut(
            QKeySequence("Ctrl+Shift+C"),
            self,
        )
        self.atalho_copiar.activated.connect(
            self.copiar_texto
        )

    def aplicar_estilo(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6f8;
            }

            QLabel#titulo {
                color: #202124;
                font-size: 22px;
                font-weight: bold;
                padding-bottom: 4px;
            }

            QScrollArea#areaRolagem {
                background-color: #ffffff;
                border: 1px solid #d9dde3;
                border-radius: 8px;
            }

            QWidget#editorTranscricao {
                background-color: #ffffff;
            }

            QFrame#containerImagem {
                background-color: #ffffff;
                border: none;
            }

            QTextEdit#editorTexto {
                background-color: #ffffff;
                color: #202124;
                border: 1px solid #d9dde3;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                selection-background-color: #cfe2ff;
            }

            QPushButton {
                background-color: #e8eaed;
                color: #202124;
                border: none;
                border-radius: 6px;
                padding: 9px 14px;
                font-size: 13px;
            }

            QPushButton:hover {
                background-color: #d9dde3;
            }

            QPushButton:disabled {
                background-color: #e8eaed;
                color: #777777;
            }

            QPushButton#botaoTranscrever {
                background-color: #1769e0;
                color: white;
                font-weight: bold;
                padding: 8px 12px;
            }

            QPushButton#botaoTranscrever:hover {
                background-color: #0f57bd;
            }

            QPushButton#botaoTranscrever:disabled {
                background-color: #7da9e8;
                color: white;
            }
        """)

    # --------------------------------------------------------
    # ABRIR IMAGEM
    # --------------------------------------------------------

    def abrir_imagem(self):
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir imagem",
            "",
            (
                "Imagens (*.png *.jpg *.jpeg *.bmp "
                "*.tif *.tiff *.webp);;Todos os arquivos (*)"
            ),
        )

        if not caminho:
            return

        imagem = QImage(caminho)

        if imagem.isNull():
            QMessageBox.warning(
                self,
                "Erro",
                "Não foi possível abrir a imagem selecionada.",
            )
            return

        self.definir_imagem(imagem)

    # --------------------------------------------------------
    # COLAR IMAGEM OU TEXTO
    # --------------------------------------------------------

    def colar_conteudo(self):
        clipboard = QApplication.clipboard()
        imagem = clipboard.image()

        if not imagem.isNull():
            self.definir_imagem(imagem)
            return

        texto = clipboard.text()

        if texto:
            if self.editor.imagem_atual is not None:
                self.editor.limpar()

            self.editor.editor_texto.show()
            self.editor.editor_texto.insertPlainText(texto)
            self.editor.editor_texto.setFocus()

            self.botao_copiar.show()

            self.statusBar().showMessage(
                "Texto colado."
            )
            return

        self.statusBar().showMessage(
            "A área de transferência não contém imagem ou texto."
        )

    # --------------------------------------------------------
    # DEFINIR IMAGEM
    # --------------------------------------------------------

    def definir_imagem(self, imagem: QImage):
        if imagem.isNull():
            return

        self.editor.definir_imagem(imagem)

        self.botao_copiar.hide()

        self.statusBar().showMessage(
            f"Imagem carregada: {imagem.width()} × "
            f"{imagem.height()} pixels"
        )

    # --------------------------------------------------------
    # TRANSCRIÇÃO
    # --------------------------------------------------------

    def transcrever_imagem(self):
        imagem = self.editor.imagem_atual

        if imagem is None:
            return

        if self.transcritor is not None:
            if self.transcritor.isRunning():
                return

        self.editor.definir_estado_transcricao(True)

        self.botao_abrir.setEnabled(False)
        self.botao_colar.setEnabled(False)
        self.botao_nova.setEnabled(False)

        self.statusBar().showMessage(
            "Transcrevendo imagem..."
        )

        self.transcritor = TranscritorOCR(
            imagem,
            self,
        )

        trabalhador = self.transcritor

        trabalhador.concluido.connect(
            self.transcricao_concluida
        )

        trabalhador.erro.connect(
            self.transcricao_com_erro
        )

        trabalhador.finished.connect(
            self.liberar_transcritor
        )

        trabalhador.start()

    def transcricao_concluida(self, texto: str):
        self.editor.mostrar_texto(texto)

        self.botao_copiar.show()

        self.statusBar().showMessage(
            "Transcrição concluída."
        )

        self.finalizar_transcricao()

    def transcricao_com_erro(self, mensagem: str):
        self.finalizar_transcricao()

        QMessageBox.critical(
            self,
            "Erro na transcrição",
            mensagem,
        )

        self.statusBar().showMessage(
            "Não foi possível concluir a transcrição."
        )

    def finalizar_transcricao(self):
        self.editor.definir_estado_transcricao(False)

        self.botao_abrir.setEnabled(True)
        self.botao_colar.setEnabled(True)
        self.botao_nova.setEnabled(True)

    def liberar_transcritor(self):
        trabalhador = self.sender()

        if trabalhador is self.transcritor:
            self.transcritor = None

        trabalhador.deleteLater()

    # --------------------------------------------------------
    # COPIAR TEXTO
    # --------------------------------------------------------

    def copiar_texto(self):
        texto = self.editor.editor_texto.toPlainText()

        if not texto.strip():
            self.statusBar().showMessage(
                "Não há texto para copiar."
            )
            return

        QApplication.clipboard().setText(texto)

        self.statusBar().showMessage(
            "Texto copiado para a área de transferência."
        )

    # --------------------------------------------------------
    # NOVA IMAGEM
    # --------------------------------------------------------

    def nova_imagem(self):
        self.editor.limpar()

        self.botao_copiar.hide()

        self.statusBar().showMessage(
            "Aguardando uma nova imagem."
        )

    # --------------------------------------------------------
    # FECHAMENTO
    # --------------------------------------------------------

    def closeEvent(self, evento):
        if (
            self.transcritor is not None
            and self.transcritor.isRunning()
        ):
            QMessageBox.information(
                self,
                "Transcrição em andamento",
                "Aguarde a conclusão da transcrição "
                "antes de fechar o aplicativo.",
            )
            evento.ignore()
            return

        evento.accept()


# ============================================================
# EXECUÇÃO
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(TITULO_JANELA)

    janela = JanelaPrincipal()
    janela.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
