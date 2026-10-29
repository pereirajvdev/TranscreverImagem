import shutil
import sys
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image

from PySide6.QtCore import Qt, QThread, Signal, QBuffer, QIODevice, QUrl
from PySide6.QtGui import (
    QAction,
    QImage,
    QKeySequence,
    QPixmap,
    QTextCursor,
    QTextImageFormat,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
class EditorTranscricao(QTextEdit):
    imagem_colada = Signal(QImage)
    mouse_sobre_imagem = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAcceptRichText(False)
        self.setMouseTracking(True)

        self.imagem_atual = None
        self.url_imagem = QUrl("transcreverimagem://imagem")

    def insertFromMimeData(self, fonte):
        # Se a área de transferência contiver uma imagem,
        # insere a imagem diretamente no editor.
        if fonte.hasImage():
            dados = fonte.imageData()

            if isinstance(dados, QPixmap):
                imagem = dados.toImage()
            elif isinstance(dados, QImage):
                imagem = dados
            else:
                return

            if imagem.isNull():
                return

            self.inserir_imagem(imagem)
            self.imagem_colada.emit(imagem)
            return

        # Mantém a colagem normal de textos.
        super().insertFromMimeData(fonte)

    def inserir_imagem(self, imagem: QImage):
        if imagem.isNull():
            return

        self.imagem_atual = imagem.copy()

        # Limpa o documento antes de registrar a imagem.
        self.clear()

        self.document().addResource(
            QTextDocument.ResourceType.ImageResource,
            self.url_imagem,
            self.imagem_atual,
        )

        formato = QTextImageFormat()
        formato.setName(self.url_imagem.toString())

        # Limita a largura ao espaço disponível no editor.
        largura_maxima = max(100, self.viewport().width() - 30)

        imagem_exibida = self.imagem_atual

        if imagem_exibida.width() > largura_maxima:
            imagem_exibida = imagem_exibida.scaledToWidth(
                largura_maxima,
                Qt.TransformationMode.SmoothTransformation,
            )

        formato.setWidth(imagem_exibida.width())
        formato.setHeight(imagem_exibida.height())

        cursor = self.textCursor()
        cursor.insertImage(formato)

        self.setTextCursor(cursor)
        self.setFocus()

    def mouseMoveEvent(self, evento):
        cursor = self.cursorForPosition(
            evento.position().toPoint()
        )

        formato = cursor.charFormat()

        sobre_imagem = (
            formato.objectType()
            == QTextFormat.ImageObject
        )

        # Verifica também o caractere anterior.
        if not sobre_imagem and cursor.position() > 0:
            cursor_anterior = QTextCursor(cursor)

            cursor_anterior.movePosition(
                QTextCursor.MoveOperation.PreviousCharacter
            )

            formato_anterior = cursor_anterior.charFormat()

            sobre_imagem = (
                formato_anterior.objectType()
                == QTextFormat.ImageObject
            )

        self.mouse_sobre_imagem.emit(sobre_imagem)

        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento):
        self.mouse_sobre_imagem.emit(False)
        super().leaveEvent(evento)


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

        titulo = QLabel("TranscreverImagem")
        titulo.setObjectName("titulo")

        subtitulo = QLabel(
            "Cole uma imagem com Ctrl+V ou digite seu texto."
        )
        subtitulo.setObjectName("subtitulo")

        layout_principal.addWidget(titulo)
        layout_principal.addWidget(subtitulo)

        # Um único campo para imagens e textos.
        self.editor_texto = EditorTranscricao()
        self.editor_texto.setObjectName("editorTexto")
        self.editor_texto.setPlaceholderText(
            "Digite seu texto ou cole uma imagem aqui..."
        )

        self.editor_texto.imagem_colada.connect(
            self.imagem_recebida
        )

        self.editor_texto.mouse_sobre_imagem.connect(
            self.alternar_botao_transcrever
        )

        layout_principal.addWidget(
            self.editor_texto,
            stretch=1,
        )

        barra_botoes = QHBoxLayout()
        barra_botoes.setSpacing(10)

        self.botao_transcrever = QPushButton("Transcrever")
        self.botao_transcrever.setObjectName("botaoPrincipal")
        self.botao_transcrever.setMinimumHeight(38)
        self.botao_transcrever.clicked.connect(
            self.transcrever_imagem
        )
        self.botao_transcrever.hide()

        self.botao_copiar = QPushButton("Copiar texto")
        self.botao_copiar.setMinimumHeight(38)
        self.botao_copiar.clicked.connect(
            self.copiar_texto
        )
        self.botao_copiar.hide()

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

        # O cursor já fica pronto para digitação.
        self.editor_texto.setFocus()

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
        imagem = clipboard.image()

        if not imagem.isNull():
            self.editor_texto.inserir_imagem(imagem)
            self.imagem_recebida(imagem)
            return

        mime_data = clipboard.mimeData()

        if mime_data.hasText():
            self.editor_texto.setFocus()
            self.editor_texto.insertPlainText(
                mime_data.text()
            )
            return

        self.statusBar().showMessage(
            "Nenhuma imagem encontrada na área de transferência."
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


    def imagem_recebida(self, imagem):
        self.botao_transcrever.hide()
        self.botao_copiar.hide()

        self.statusBar().showMessage(
            f"Imagem carregada: "
            f"{imagem.width()} × {imagem.height()} pixels"
        )


    def alternar_botao_transcrever(self, sobre_imagem):
        tem_imagem = self.editor_texto.imagem_atual is not None

        self.botao_transcrever.setVisible(
            sobre_imagem
            and tem_imagem
            and self.botao_transcrever.isEnabled()
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
        if self.editor_texto.imagem_atual is None:
            return

        self.botao_transcrever.setEnabled(False)
        self.botao_transcrever.setText("Transcrevendo...")
        self.statusBar().showMessage(
            "Reconhecendo os textos da imagem..."
        )

        self.transcritor = TranscritorOCR(
            self.editor_texto.imagem_atual
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
        self.editor_texto.imagem_atual = None
        self.editor_texto.setFocus()

        self.botao_transcrever.hide()
        self.botao_copiar.show()

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