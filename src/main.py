import shutil
import sys
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image

from PySide6.QtCore import Qt, QThread, Signal, QBuffer, QIODevice
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut, QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
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

if CAMINHO_TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(
        CAMINHO_TESSERACT
    )
else:
    CAMINHO_TESSERACT = None


# ============================================================
# THREAD DE RECONHECIMENTO DE TEXTO
# ============================================================

class TranscritorOCR(QThread):
    concluido = Signal(str)
    erro = Signal(str)

    def __init__(self, imagem: QImage):
        super().__init__()
        self.imagem = imagem.copy()

    def run(self):
        try:
            if not CAMINHO_TESSERACT:
                raise RuntimeError(
                    "Tesseract OCR não encontrado.\n\n"
                    "Instale o Tesseract OCR ou configure "
                    "o caminho do executável no código."
                )

            # Converte QImage para uma imagem PIL.
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)

            if not self.imagem.save(buffer, "PNG"):
                raise RuntimeError(
                    "Não foi possível preparar a imagem."
                )

            dados = bytes(buffer.data())
            buffer.close()

            with Image.open(BytesIO(dados)) as imagem:
                imagem = imagem.convert("RGB")

                # Reconhece português e inglês.
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
# JANELA PRINCIPAL
# ============================================================

class JanelaPrincipal(QMainWindow):

    def __init__(self):
        super().__init__()

        self.imagem_atual = None
        self.transcritor = None

        self.setWindowTitle(TITULO_JANELA)
        self.resize(950, 650)
        self.setMinimumSize(650, 450)

        self.criar_interface()
        self.criar_menu()
        self.configurar_atalhos()
        self.aplicar_estilo()

    # --------------------------------------------------------
    # INTERFACE
    # --------------------------------------------------------

    def criar_interface(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout_principal = QVBoxLayout(central)
        layout_principal.setContentsMargins(18, 18, 18, 14)
        layout_principal.setSpacing(12)

        # Cabeçalho.
        titulo = QLabel("TranscreverImagem")
        titulo.setObjectName("titulo")

        subtitulo = QLabel(
            "Cole uma imagem com Ctrl+V para começar."
        )
        subtitulo.setObjectName("subtitulo")

        layout_principal.addWidget(titulo)
        layout_principal.addWidget(subtitulo)

        # Área principal: imagem ou texto transcrito.
        self.area_conteudo = QStackedWidget()
        self.area_conteudo.setObjectName("areaConteudo")

        # Página de imagem.
        self.area_imagem = QLabel()
        self.area_imagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.area_imagem.setMinimumSize(300, 250)
        self.area_imagem.setText(
            "Cole uma imagem aqui usando Ctrl+V\n\n"
            "Você pode copiar uma captura de tela,\n"
            "uma imagem do Paint ou de outro aplicativo."
        )
        self.area_imagem.setObjectName("areaImagem")

        # Página de texto.
        self.editor_texto = QTextEdit()
        self.editor_texto.setPlaceholderText(
            "O texto reconhecido aparecerá aqui..."
        )
        self.editor_texto.setObjectName("editorTexto")
        self.editor_texto.setAcceptRichText(False)

        self.area_conteudo.addWidget(self.area_imagem)
        self.area_conteudo.addWidget(self.editor_texto)

        layout_principal.addWidget(
            self.area_conteudo,
            stretch=1,
        )

        # Barra inferior.
        barra_botoes = QHBoxLayout()
        barra_botoes.setSpacing(10)

        self.botao_transcrever = QPushButton("Transcrever")
        self.botao_transcrever.setObjectName("botaoPrincipal")
        self.botao_transcrever.setMinimumHeight(38)
        self.botao_transcrever.clicked.connect(
            self.transcrever_imagem
        )
        self.botao_transcrever.setVisible(False)

        self.botao_copiar = QPushButton("Copiar texto")
        self.botao_copiar.setMinimumHeight(38)
        self.botao_copiar.clicked.connect(
            self.copiar_texto
        )

        self.botao_copiar.setVisible(False)

        self.botao_nova_imagem = QPushButton("Nova imagem")
        self.botao_nova_imagem.setMinimumHeight(38)
        self.botao_nova_imagem.clicked.connect(
            self.paste_image
        )

        barra_botoes.addWidget(self.botao_transcrever)
        barra_botoes.addWidget(self.botao_copiar)
        barra_botoes.addStretch()
        barra_botoes.addWidget(self.botao_nova_imagem)

        layout_principal.addLayout(barra_botoes)

        self.statusBar().showMessage("Pronto")

    # --------------------------------------------------------
    # MENU
    # --------------------------------------------------------

    def criar_menu(self):
        menu_arquivo = self.menuBar().addMenu("Arquivo")
        menu_editar = self.menuBar().addMenu("Editar")

        acao_abrir = QAction("Abrir imagem...", self)
        acao_abrir.setShortcut("Ctrl+O")
        acao_abrir.triggered.connect(self.abrir_imagem)

        acao_salvar = QAction("Salvar texto...", self)
        acao_salvar.setShortcut("Ctrl+S")
        acao_salvar.triggered.connect(self.salvar_texto)

        acao_sair = QAction("Sair", self)
        acao_sair.triggered.connect(self.close)

        acao_colar = QAction("Colar imagem", self)
        acao_colar.setShortcut("Ctrl+V")
        acao_colar.triggered.connect(self.paste_image)

        menu_arquivo.addAction(acao_abrir)
        menu_arquivo.addAction(acao_salvar)
        menu_arquivo.addSeparator()
        menu_arquivo.addAction(acao_sair)

        menu_editar.addAction(acao_colar)

    # --------------------------------------------------------
    # ATALHOS
    # --------------------------------------------------------

    def configurar_atalhos(self):
        self.atalho_colar = QShortcut(
            QKeySequence.StandardKey.Paste,
            self,
        )
        self.atalho_colar.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.atalho_colar.activated.connect(self.paste_image)

    # --------------------------------------------------------
    # COLAR IMAGEM
    # --------------------------------------------------------

    def paste_image(self):
        clipboard = QApplication.clipboard()

        if clipboard.mimeData().hasImage():
            imagem = clipboard.image()

            if imagem.isNull():
                self.statusBar().showMessage(
                    "Não foi possível ler a imagem."
                )
                return

            self.definir_imagem(imagem)
            return

        # Se o usuário estiver editando o texto, permite
        # continuar usando Ctrl+V para colar texto normalmente.
        if self.area_conteudo.currentWidget() == self.editor_texto:
            self.editor_texto.paste()
        else:
            self.statusBar().showMessage(
                "A área de transferência não contém uma imagem."
            )

    def definir_imagem(self, imagem: QImage):
        self.imagem_atual = imagem.copy()

        pixmap = QPixmap.fromImage(self.imagem_atual)

        pixmap_ajustado = pixmap.scaled(
            self.area_imagem.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.area_imagem.setPixmap(pixmap_ajustado)

        self.area_conteudo.setCurrentWidget(self.area_imagem)

        self.botao_transcrever.setVisible(True)
        self.botao_copiar.setVisible(False)

        self.statusBar().showMessage(
            f"Imagem carregada: "
            f"{imagem.width()} × {imagem.height()} pixels"
        )

    def resizeEvent(self, evento):
        super().resizeEvent(evento)

        if self.imagem_atual is not None:
            if (
                self.area_conteudo.currentWidget()
                == self.area_imagem
            ):
                pixmap = QPixmap.fromImage(self.imagem_atual)

                self.area_imagem.setPixmap(
                    pixmap.scaled(
                        self.area_imagem.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    # --------------------------------------------------------
    # ABRIR IMAGEM
    # --------------------------------------------------------

    def abrir_imagem(self):
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir imagem",
            "",
            (
                "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
                "Todos os arquivos (*)"
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
    # TRANSCRIÇÃO
    # --------------------------------------------------------

    def transcrever_imagem(self):
        if self.imagem_atual is None:
            return

        self.botao_transcrever.setEnabled(False)
        self.botao_transcrever.setText("Transcrevendo...")
        self.statusBar().showMessage(
            "Reconhecendo os textos da imagem..."
        )

        self.transcritor = TranscritorOCR(
            self.imagem_atual
        )

        self.transcritor.concluido.connect(
            self.transcricao_concluida
        )
        self.transcritor.erro.connect(
            self.transcricao_com_erro
        )
        self.transcritor.finished.connect(
            self.transcritor.deleteLater
        )

        self.transcritor.start()

    def transcricao_concluida(self, texto: str):
        self.editor_texto.setPlainText(texto)

        # O texto ocupa a mesma área central da imagem.
        self.area_conteudo.setCurrentWidget(
            self.editor_texto
        )

        self.botao_transcrever.setVisible(False)
        self.botao_copiar.setVisible(True)

        self.statusBar().showMessage(
            "Transcrição concluída."
        )

        self.finalizar_transcricao()

    def transcricao_com_erro(self, mensagem: str):
        QMessageBox.critical(
            self,
            "Erro na transcrição",
            (
                "Não foi possível transcrever a imagem.\n\n"
                f"{mensagem}\n\n"
                "Verifique se o Tesseract está instalado e "
                "se os idiomas por e eng estão disponíveis."
            ),
        )

        self.statusBar().showMessage(
            "Falha na transcrição."
        )

        self.finalizar_transcricao()

    def finalizar_transcricao(self):
        self.botao_transcrever.setEnabled(True)
        self.botao_transcrever.setText("Transcrever")
        self.transcritor = None

    # --------------------------------------------------------
    # TEXTO
    # --------------------------------------------------------

    def copiar_texto(self):
        texto = self.editor_texto.toPlainText()

        if not texto:
            return

        QApplication.clipboard().setText(texto)
        self.statusBar().showMessage(
            "Texto copiado para a área de transferência."
        )

    def salvar_texto(self):
        caminho, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar texto transcrito",
            "transcricao.txt",
            "Arquivos de texto (*.txt);;Todos os arquivos (*)",
        )

        if not caminho:
            return

        try:
            Path(caminho).write_text(
                self.editor_texto.toPlainText(),
                encoding="utf-8",
            )

            self.statusBar().showMessage(
                "Texto salvo com sucesso."
            )

        except OSError as exc:
            QMessageBox.critical(
                self,
                "Erro ao salvar",
                str(exc),
            )

    # --------------------------------------------------------
    # ESTILO
    # --------------------------------------------------------

    def aplicar_estilo(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6f8;
            }

            QLabel#titulo {
                color: #202124;
                font-size: 23px;
                font-weight: bold;
            }

            QLabel#subtitulo {
                color: #666b73;
                font-size: 13px;
                padding-bottom: 5px;
            }

            QStackedWidget {
                background-color: white;
                border: 1px solid #d8dce2;
                border-radius: 8px;
            }

            QLabel#areaImagem {
                color: #737983;
                background-color: white;
                padding: 12px;
            }

            QTextEdit#editorTexto {
                color: #202124;
                background-color: white;
                border: none;
                padding: 14px;
                font-family: Consolas;
                font-size: 14px;
                selection-background-color: #c9ddff;
            }

            QPushButton {
                background-color: white;
                color: #30343b;
                border: 1px solid #d0d5dc;
                border-radius: 5px;
                padding: 8px 16px;
            }

            QPushButton:hover {
                background-color: #edf1f7;
            }

            QPushButton:disabled {
                color: #8b9098;
            }

            QPushButton#botaoPrincipal {
                background-color: #2463eb;
                color: white;
                border: none;
                font-weight: bold;
                min-width: 110px;
            }

            QPushButton#botaoPrincipal:hover {
                background-color: #1d4fc4;
            }

            QMenuBar {
                background-color: #f5f6f8;
                color: #202124;
            }

            QMenuBar::item:selected {
                background-color: #e4e8ef;
            }

            QStatusBar {
                color: #626873;
            }
        """)


# ============================================================
# INICIALIZAÇÃO
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(TITULO_JANELA)

    janela = JanelaPrincipal()
    janela.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()