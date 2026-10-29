import sys
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image

from PySide6.QtCore import (
    Qt,
    QThread,
    Signal,
    QBuffer,
    QIODevice,
    QMimeData,
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QUrl,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolTip,
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

# Valor usado quando nenhuma imagem está selecionada.
SEM_IMAGEM = -1

# Prefixo do "nome" de cada imagem dentro do documento.
# O nome completo é "imagem://local/<id>".
PREFIXO_IMAGEM = "imagem://local/"


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
    # Ambos os sinais carregam o id da imagem transcrita.
    concluido = Signal(int, str)
    erro = Signal(int, str)

    def __init__(self, id_imagem: int, imagem: QImage, parent=None):
        super().__init__(parent)
        self.id_imagem = id_imagem
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

            # Remove o caractere de quebra de página do Tesseract
            # e espaços sobrando nas pontas.
            texto = texto.replace("\x0c", "").strip()

            if not texto:
                texto = (
                    "Nenhum texto foi identificado na imagem."
                )

            self.concluido.emit(self.id_imagem, texto)

        except Exception as exc:
            self.erro.emit(self.id_imagem, str(exc))


# ============================================================
# EDITOR DE IMAGENS E TEXTO
# ============================================================

class EditorTexto(QTextEdit):
    # Emitido quando uma imagem é inserida (envia o id dela).
    imagem_inserida = Signal(int)

    # Emitido quando a seleção muda. Envia o id da imagem
    # selecionada ou SEM_IMAGEM.
    imagem_selecionada = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        # id -> QImage (imagem original, em tamanho real)
        self.imagens = {}
        self._proximo_id = 1
        self.id_selecionado = SEM_IMAGEM

        self.selectionChanged.connect(self._atualizar_selecao)
        self.cursorPositionChanged.connect(
            self._atualizar_selecao
        )

    # --------------------------------------------------------
    # Utilitários de documento
    # --------------------------------------------------------

    @staticmethod
    def fragmentos(bloco):
        it = bloco.begin()

        while not it.atEnd():
            fragmento = it.fragment()

            if fragmento.isValid():
                yield fragmento

            it += 1

    @staticmethod
    def id_do_formato(formato: QTextImageFormat):
        nome = formato.name()

        if not nome.startswith(PREFIXO_IMAGEM):
            return None

        try:
            return int(nome[len(PREFIXO_IMAGEM):])
        except ValueError:
            return None

    def imagem_no_bloco(self, bloco):
        """Retorna (posição, formato) da imagem do bloco ou None."""
        for fragmento in self.fragmentos(bloco):
            formato = fragmento.charFormat()

            if formato.isImageFormat():
                return (
                    fragmento.position(),
                    formato.toImageFormat(),
                )

        return None

    def bloco_contem_imagem(self, bloco):
        return self.imagem_no_bloco(bloco) is not None

    def bloco_da_imagem(self, id_imagem: int):
        """Localiza o bloco que contém a imagem com o id informado."""
        bloco = self.document().begin()

        while bloco.isValid():
            achado = self.imagem_no_bloco(bloco)

            if achado is not None:
                _, formato = achado

                if self.id_do_formato(formato) == id_imagem:
                    return bloco

            bloco = bloco.next()

        return None

    def ids_na_selecao(self, cursor: QTextCursor):
        """Ids de todas as imagens (nossas) dentro da seleção."""
        if not cursor.hasSelection():
            return []

        inicio = cursor.selectionStart()
        fim = cursor.selectionEnd()

        ids = []
        bloco = self.document().findBlock(inicio)

        while bloco.isValid() and bloco.position() < fim:
            for fragmento in self.fragmentos(bloco):
                formato = fragmento.charFormat()

                if (
                    formato.isImageFormat()
                    and inicio <= fragmento.position() < fim
                ):
                    id_imagem = self.id_do_formato(
                        formato.toImageFormat()
                    )

                    if id_imagem in self.imagens:
                        ids.append(id_imagem)

            bloco = bloco.next()

        return ids

    # --------------------------------------------------------
    # Inserção de imagens
    # --------------------------------------------------------

    def inserir_imagem(self, imagem: QImage) -> int:
        """Insere a imagem em um parágrafo próprio e devolve o id."""
        id_imagem = self._proximo_id
        self._proximo_id += 1

        self.imagens[id_imagem] = imagem.copy()

        nome = f"{PREFIXO_IMAGEM}{id_imagem}"

        self.document().addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(nome),
            imagem,
        )

        # Reduz para caber na largura do editor (sem distorcer).
        largura_maxima = max(self.viewport().width() - 40, 100)
        largura = imagem.width()
        altura = imagem.height()

        if largura > largura_maxima:
            altura = round(altura * largura_maxima / largura)
            largura = largura_maxima

        formato = QTextImageFormat()
        formato.setName(nome)
        formato.setWidth(largura)
        formato.setHeight(altura)

        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.clearSelection()

        # Se a linha atual já tem conteúdo, começa uma nova.
        if cursor.block().length() > 1:
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock
            )
            cursor.insertBlock(
                QTextBlockFormat(),
                QTextCharFormat(),
            )

        cursor.insertImage(formato)

        # Linha vazia depois da imagem, sem herdar o formato dela.
        cursor.insertBlock(
            QTextBlockFormat(),
            QTextCharFormat(),
        )

        cursor.endEditBlock()

        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.setFocus()

        self.imagem_inserida.emit(id_imagem)

        return id_imagem

    def inserir_transcricao(self, id_imagem: int, texto: str):
        """Insere o texto logo abaixo da imagem com o id informado."""
        cursor = self.textCursor()
        cursor.beginEditBlock()

        bloco = self.bloco_da_imagem(id_imagem)

        if bloco is not None:
            cursor.setPosition(bloco.position())
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock
            )
        else:
            # A imagem foi removida: acrescenta ao final.
            cursor.movePosition(
                QTextCursor.MoveOperation.End
            )

        cursor.insertBlock(
            QTextBlockFormat(),
            QTextCharFormat(),
        )
        cursor.insertText(texto, QTextCharFormat())

        cursor.endEditBlock()

        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.setFocus()

    def limpar_conteudo(self):
        self.clear()
        self.imagens.clear()
        self._proximo_id = 1
        self._atualizar_selecao()

    # --------------------------------------------------------
    # Seleção de imagens
    # --------------------------------------------------------

    def _atualizar_selecao(self):
        ids = self.ids_na_selecao(self.textCursor())

        # O botão só faz sentido com exatamente uma imagem.
        novo_id = ids[0] if len(ids) == 1 else SEM_IMAGEM

        if novo_id != self.id_selecionado:
            self.id_selecionado = novo_id
            self.imagem_selecionada.emit(novo_id)

    def imagem_na_posicao(self, ponto: QPoint):
        """
        Retorna (posição, id) se o ponto (coordenadas do viewport)
        estiver sobre uma imagem; caso contrário, None.
        """
        layout = self.document().documentLayout()

        x = ponto.x() + self.horizontalScrollBar().value()
        y = ponto.y() + self.verticalScrollBar().value()
        ponto_documento = QPointF(x, y)

        bloco = self.cursorForPosition(ponto).block()

        for candidato in (
            bloco,
            bloco.previous(),
            bloco.next(),
        ):
            if not candidato.isValid():
                continue

            achado = self.imagem_no_bloco(candidato)

            if achado is None:
                continue

            posicao, formato = achado
            id_imagem = self.id_do_formato(formato)

            if id_imagem not in self.imagens:
                continue

            retangulo = layout.blockBoundingRect(candidato)
            area = QRectF(
                retangulo.left(),
                retangulo.top(),
                formato.width(),
                formato.height(),
            )

            if area.contains(ponto_documento):
                return posicao, id_imagem

        return None

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            achado = self.imagem_na_posicao(
                evento.position().toPoint()
            )

            if achado is not None:
                posicao, _ = achado

                cursor = self.textCursor()
                cursor.setPosition(posicao)
                cursor.setPosition(
                    posicao + 1,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self.setTextCursor(cursor)
                self.setFocus(Qt.FocusReason.MouseFocusReason)

                evento.accept()
                return

        super().mousePressEvent(evento)

    def viewportEvent(self, evento):
        # Mostra o id da imagem ao passar o mouse sobre ela.
        if evento.type() == QEvent.Type.ToolTip:
            achado = self.imagem_na_posicao(evento.pos())

            if achado is not None:
                QToolTip.showText(
                    evento.globalPos(),
                    f"Imagem #{achado[1]}",
                    self.viewport(),
                )
            else:
                QToolTip.hideText()

            return True

        return super().viewportEvent(evento)

    # --------------------------------------------------------
    # Teclado
    # --------------------------------------------------------

    def pular_linha_da_imagem(self):
        cursor = self.textCursor()
        bloco = cursor.block()

        achado = self.imagem_no_bloco(bloco)

        if achado is None:
            return False

        posicao_imagem, _ = achado

        cursor.beginEditBlock()

        # Cursor antes da imagem: cria uma linha acima dela.
        if cursor.position() <= posicao_imagem:
            cursor.setPosition(bloco.position())
            cursor.insertBlock(
                QTextBlockFormat(),
                QTextCharFormat(),
            )

            cursor.movePosition(
                QTextCursor.MoveOperation.PreviousBlock
            )
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock
            )

        # Cursor depois da imagem: cria uma linha abaixo dela.
        else:
            cursor.setPosition(bloco.position())
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock
            )
            cursor.insertBlock(
                QTextBlockFormat(),
                QTextCharFormat(),
            )

        cursor.endEditBlock()

        self.setTextCursor(cursor)
        return True

    def keyPressEvent(self, evento):
        modificadores = evento.modifiers()
        texto = evento.text()

        sem_atalho = not (
            modificadores
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
            )
        )

        # Só caracteres imprimíveis (Backspace/Delete não entram).
        digitando = (
            sem_atalho
            and bool(texto)
            and texto.isprintable()
        )

        enter = evento.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        )

        if digitando or enter:
            cursor = self.textCursor()

            # Evita que digitar apague uma imagem selecionada.
            if cursor.hasSelection() and self.ids_na_selecao(cursor):
                cursor.clearSelection()
                self.setTextCursor(cursor)

            pulou = self.pular_linha_da_imagem()

            # Enter na linha da imagem só abre a linha vazia.
            if pulou and enter:
                return

        super().keyPressEvent(evento)

    # --------------------------------------------------------
    # Área de transferência
    # --------------------------------------------------------

    def canInsertFromMimeData(self, source: QMimeData):
        return source.hasImage() or super().canInsertFromMimeData(
            source
        )

    def insertFromMimeData(self, source: QMimeData):
        if source.hasImage():
            dado = source.imageData()
            imagem = None

            if isinstance(dado, QImage):
                imagem = dado
            elif isinstance(dado, QPixmap):
                imagem = dado.toImage()

            if imagem is not None and not imagem.isNull():
                self.inserir_imagem(imagem.copy())
                return

        # Texto colado sobre o parágrafo da imagem vai para
        # um parágrafo adjacente.
        if self.bloco_contem_imagem(self.textCursor().block()):
            self.pular_linha_da_imagem()

        super().insertFromMimeData(source)

    def createMimeDataFromSelection(self):
        # Copiar/recortar uma imagem selecionada coloca a própria
        # imagem na área de transferência. Ao colar, ela vira uma
        # nova imagem, com um novo id.
        cursor = self.textCursor()
        ids = self.ids_na_selecao(cursor)

        if len(ids) == 1:
            restante = cursor.selectedText().replace("\ufffc", "")

            if not restante.strip():
                mime = QMimeData()
                mime.setImageData(self.imagens[ids[0]])
                return mime

        return super().createMimeDataFromSelection()


class EditorTranscricao(QWidget):
    imagem_inserida = Signal(int)
    imagem_selecionada = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("editorTranscricao")

        self.criar_interface()

    @property
    def id_selecionado(self) -> int:
        return self.editor_texto.id_selecionado

    def criar_interface(self):
        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        self.editor_texto = EditorTexto(self)
        self.editor_texto.setObjectName("editorTexto")
        self.editor_texto.setAcceptRichText(True)
        self.editor_texto.setPlaceholderText(
            "Cole imagens ou digite seu texto..."
        )

        self.editor_texto.imagem_inserida.connect(
            self.imagem_inserida.emit
        )
        self.editor_texto.imagem_selecionada.connect(
            self.imagem_selecionada.emit
        )

        layout_principal.addWidget(
            self.editor_texto,
            stretch=1,
        )

    def adicionar_imagem(self, imagem: QImage) -> int:
        return self.editor_texto.inserir_imagem(imagem)

    def obter_imagem(self, id_imagem: int):
        return self.editor_texto.imagens.get(id_imagem)

    def mostrar_texto(self, id_imagem: int, texto: str):
        self.editor_texto.inserir_transcricao(id_imagem, texto)

    def limpar(self):
        self.editor_texto.limpar_conteudo()
        self.editor_texto.setFocus()


# ============================================================
# JANELA PRINCIPAL
# ============================================================

class JanelaPrincipal(QMainWindow):

    def __init__(self):
        super().__init__()

        self.transcritor = None
        self.em_transcricao = False

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

        # Botão de transcrição: aparece só com uma imagem selecionada.
        self.botao_transcrever = QPushButton("Transcrever")
        self.botao_transcrever.setObjectName(
            "botaoTranscrever"
        )
        self.botao_transcrever.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_transcrever.clicked.connect(
            self.transcrever_imagem
        )

        # Mantém o espaço reservado quando oculto, para o
        # editor não "pular" ao selecionar/desselecionar.
        politica = self.botao_transcrever.sizePolicy()
        politica.setRetainSizeWhenHidden(True)
        self.botao_transcrever.setSizePolicy(politica)

        self.botao_transcrever.hide()

        layout_principal.addWidget(
            self.botao_transcrever,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

        # Editor
        self.editor = EditorTranscricao(self)

        layout_principal.addWidget(
            self.editor,
            stretch=1,
        )

        # Botões inferiores
        layout_botoes = QHBoxLayout()
        layout_botoes.setSpacing(8)

        self.botao_abrir = QPushButton("Abrir imagens")
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

        self.botao_limpar = QPushButton("Limpar tudo")
        self.botao_limpar.clicked.connect(
            self.limpar_editor
        )

        layout_botoes.addWidget(self.botao_abrir)
        layout_botoes.addWidget(self.botao_colar)
        layout_botoes.addStretch()
        layout_botoes.addWidget(self.botao_copiar)
        layout_botoes.addWidget(self.botao_limpar)

        layout_principal.addLayout(layout_botoes)

        # Conexões do editor
        self.editor.imagem_inserida.connect(
            self.ao_inserir_imagem
        )
        self.editor.imagem_selecionada.connect(
            self.ao_selecionar_imagem
        )
        self.editor.editor_texto.textChanged.connect(
            self.atualizar_botao_copiar
        )

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

            QWidget#editorTranscricao {
                background-color: #ffffff;
            }

            QTextEdit#editorTexto {
                background-color: #ffffff;
                color: #202124;
                border: 1px solid #d9dde3;
                border-radius: 8px;
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
    # ESTADO DOS BOTÕES
    # --------------------------------------------------------

    def atualizar_botao_transcrever(self):
        id_imagem = self.editor.id_selecionado

        if id_imagem == SEM_IMAGEM:
            self.botao_transcrever.hide()
            return

        if self.em_transcricao:
            self.botao_transcrever.setText("Transcrevendo...")
            self.botao_transcrever.setEnabled(False)
        else:
            self.botao_transcrever.setText(
                f"Transcrever imagem #{id_imagem}"
            )
            self.botao_transcrever.setEnabled(True)

        self.botao_transcrever.show()

    def atualizar_botao_copiar(self):
        texto = self.editor.editor_texto.toPlainText()
        texto = texto.replace("\ufffc", "")

        self.botao_copiar.setVisible(bool(texto.strip()))

    # --------------------------------------------------------
    # EVENTOS DO EDITOR
    # --------------------------------------------------------

    def ao_inserir_imagem(self, id_imagem: int):
        imagem = self.editor.obter_imagem(id_imagem)

        if imagem is None:
            return

        self.statusBar().showMessage(
            f"Imagem #{id_imagem} adicionada "
            f"({imagem.width()} × {imagem.height()} pixels). "
            "Clique nela para selecioná-la e transcrever."
        )

    def ao_selecionar_imagem(self, id_imagem: int):
        self.atualizar_botao_transcrever()

        if id_imagem != SEM_IMAGEM:
            self.statusBar().showMessage(
                f"Imagem #{id_imagem} selecionada."
            )

    # --------------------------------------------------------
    # ABRIR IMAGENS
    # --------------------------------------------------------

    def abrir_imagem(self):
        caminhos, _ = QFileDialog.getOpenFileNames(
            self,
            "Abrir imagens",
            "",
            (
                "Imagens (*.png *.jpg *.jpeg *.bmp "
                "*.tif *.tiff *.webp);;Todos os arquivos (*)"
            ),
        )

        if not caminhos:
            return

        falhas = []

        for caminho in caminhos:
            imagem = QImage(caminho)

            if imagem.isNull():
                falhas.append(Path(caminho).name)
                continue

            self.editor.adicionar_imagem(imagem)

        if falhas:
            QMessageBox.warning(
                self,
                "Erro",
                "Não foi possível abrir:\n\n"
                + "\n".join(falhas),
            )

    # --------------------------------------------------------
    # COLAR IMAGEM OU TEXTO
    # --------------------------------------------------------

    def colar_conteudo(self):
        clipboard = QApplication.clipboard()

        imagem = clipboard.image()

        if not imagem.isNull():
            self.editor.adicionar_imagem(imagem)
            return

        texto = clipboard.text()

        if texto:
            editor = self.editor.editor_texto

            editor.setFocus()
            editor.pular_linha_da_imagem()
            editor.insertPlainText(texto)

            self.statusBar().showMessage("Texto colado.")
            return

        self.statusBar().showMessage(
            "A área de transferência não contém imagem ou texto."
        )

    # --------------------------------------------------------
    # TRANSCRIÇÃO
    # --------------------------------------------------------

    def transcrever_imagem(self):
        if self.em_transcricao:
            return

        id_imagem = self.editor.id_selecionado

        if id_imagem == SEM_IMAGEM:
            return

        imagem = self.editor.obter_imagem(id_imagem)

        if imagem is None or imagem.isNull():
            return

        self.em_transcricao = True
        self.atualizar_botao_transcrever()

        self.botao_abrir.setEnabled(False)
        self.botao_colar.setEnabled(False)
        self.botao_limpar.setEnabled(False)

        self.statusBar().showMessage(
            f"Transcrevendo imagem #{id_imagem}..."
        )

        self.transcritor = TranscritorOCR(
            id_imagem,
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

    def transcricao_concluida(self, id_imagem: int, texto: str):
        self.editor.mostrar_texto(id_imagem, texto)

        self.finalizar_transcricao()

        self.statusBar().showMessage(
            f"Transcrição da imagem #{id_imagem} concluída."
        )

    def transcricao_com_erro(self, id_imagem: int, mensagem: str):
        self.finalizar_transcricao()

        QMessageBox.critical(
            self,
            "Erro na transcrição",
            mensagem,
        )

        self.statusBar().showMessage(
            f"Não foi possível transcrever a imagem #{id_imagem}."
        )

    def finalizar_transcricao(self):
        self.em_transcricao = False
        self.atualizar_botao_transcrever()

        self.botao_abrir.setEnabled(True)
        self.botao_colar.setEnabled(True)
        self.botao_limpar.setEnabled(True)

    def liberar_transcritor(self):
        trabalhador = self.sender()

        if trabalhador is self.transcritor:
            self.transcritor = None

        trabalhador.deleteLater()

    # --------------------------------------------------------
    # COPIAR TEXTO
    # --------------------------------------------------------

    def copiar_texto(self):
        editor = self.editor.editor_texto
        cursor = editor.textCursor()

        # Com texto selecionado, copia só a seleção.
        if cursor.hasSelection():
            texto = cursor.selection().toPlainText()
        else:
            texto = editor.toPlainText()

        # Remove os marcadores que o Qt usa no lugar das imagens.
        texto = texto.replace("\ufffc", "").strip()

        if not texto:
            self.statusBar().showMessage(
                "Não há texto para copiar."
            )
            return

        QApplication.clipboard().setText(texto)

        self.statusBar().showMessage(
            "Texto copiado para a área de transferência."
        )

    # --------------------------------------------------------
    # LIMPAR TUDO
    # --------------------------------------------------------

    def limpar_editor(self):
        self.editor.limpar()

        self.statusBar().showMessage(
            "Editor limpo. Cole ou abra novas imagens."
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
