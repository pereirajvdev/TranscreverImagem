import sys
from io import BytesIO
from pathlib import Path

import pytesseract
from PIL import Image

import cv2
import numpy as np

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
                    f"Verifique o arquivo:\n{PASTA_TESSERACT}\\tesseract.exe"
                )

            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)

            if not self.imagem.save(buffer, "PNG"):
                buffer.close()
                raise RuntimeError(
                    "Não foi possível converter a imagem."
                )

            dados = bytes(buffer.data())
            buffer.close()


            with Image.open(BytesIO(dados)) as original:
                imagem = original.convert("RGB")

            # Converte a captura para tons de cinza.
            imagem_cv = cv2.cvtColor(
                np.array(imagem),
                cv2.COLOR_RGB2GRAY,
            )

            # Amplia a imagem para facilitar a leitura de textos pequenos.
            altura, largura = imagem_cv.shape

            escala = 2.0 if largura < 2500 else 1.5

            imagem_cv = cv2.resize(
                imagem_cv,
                None,
                fx=escala,
                fy=escala,
                interpolation=cv2.INTER_CUBIC,
            )

            # Melhora suavemente o contraste sem binarizar a imagem.
            imagem_cv = cv2.convertScaleAbs(
                imagem_cv,
                alpha=1.15,
                beta=5,
            )

            # Cria uma margem branca para evitar cortes nas bordas.
            imagem_cv = cv2.copyMakeBorder(
                imagem_cv,
                10, 10, 10, 10,
                cv2.BORDER_CONSTANT,
                value=255,
            )

            # Adequado como primeiro teste para um bloco de texto.
            configuracao = (
                "--oem 3 --psm 6 "
                "-c preserve_interword_spaces=1"
            )

            texto = pytesseract.image_to_string(
                imagem_cv,
                lang="por",
                config=configuracao,
            )

            texto = texto.replace("\x0c", "").strip()

            if not texto:
                texto = (
                    "Nenhum texto foi identificado na imagem."
                )

            self.concluido.emit(
                self.id_imagem,
                texto,
            )

        except Exception as exc:
            self.erro.emit(
                self.id_imagem,
                str(exc),
            )



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



class NotaWidget(QWidget):

    def __init__(self, numero: int, janela_principal, parent=None):
        super().__init__(parent)

        self.numero = numero
        self.janela_principal = janela_principal
        self.transcritor = None
        self.em_transcricao = False

        self.setObjectName("notaWidget")

        self.criar_interface()

    def criar_interface(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Cabeçalho da nota
        cabecalho = QHBoxLayout()
        cabecalho.setContentsMargins(6, 2, 4, 2)
        cabecalho.setSpacing(2)

        self.titulo = QLabel(f"Nota {self.numero}")
        self.titulo.setObjectName("tituloNota")

        self.botao_fechar = QPushButton("×")
        self.botao_fechar.setObjectName("botaoFecharNota")
        self.botao_fechar.setFixedSize(30, 30)
        self.botao_fechar.setToolTip("Fechar nota")
        self.botao_fechar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_fechar.clicked.connect(
            self.fechar_nota
        )

        cabecalho.addWidget(self.titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(self.botao_fechar)

        layout.addLayout(cabecalho)

        # Editor independente
        self.editor = EditorTranscricao(self)
        layout.addWidget(self.editor, stretch=1)

        # Botões da nota
        layout_botoes = QHBoxLayout()
        layout_botoes.setContentsMargins(4, 2, 4, 2)
        layout_botoes.setSpacing(4)

        self.botao_transcrever = QPushButton("Transcrever")
        self.botao_transcrever.setObjectName(
            "botaoTranscrever"
        )
        self.botao_transcrever.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_transcrever.hide()
        self.botao_transcrever.clicked.connect(
            self.transcrever_imagem
        )

        self.botao_copiar = QPushButton("Copiar texto")
        self.botao_copiar.hide()
        self.botao_copiar.clicked.connect(
            self.copiar_texto
        )

        layout_botoes.addWidget(self.botao_transcrever)
        layout_botoes.addStretch()
        layout_botoes.addWidget(self.botao_copiar)

        layout.addLayout(layout_botoes)

        # Eventos do editor
        self.editor.imagem_selecionada.connect(
            self.atualizar_botao_transcrever
        )

        self.editor.editor_texto.textChanged.connect(
            self.atualizar_botao_copiar
        )

        # Registrar qual nota está sendo utilizada
        self.editor.editor_texto.focusInEvent = (
            self._criar_focus_handler(
                self.editor.editor_texto.focusInEvent
            )
        )

    def _criar_focus_handler(self, handler_original):
        def handler(evento):
            self.janela_principal.nota_ativa = self
            handler_original(evento)

        return handler

    def atualizar_botao_transcrever(self, id_imagem):
        if id_imagem == SEM_IMAGEM:
            self.botao_transcrever.hide()
            return

        self.botao_transcrever.setText(
            f"Transcrever imagem #{id_imagem}"
        )

        self.botao_transcrever.setEnabled(
            not self.em_transcricao
        )

        if self.em_transcricao:
            self.botao_transcrever.setText(
                "Transcrevendo..."
            )

        self.botao_transcrever.show()

    def atualizar_botao_copiar(self):
        texto = (
            self.editor.editor_texto
            .toPlainText()
            .replace("\ufffc", "")
        )

        self.botao_copiar.setVisible(
            bool(texto.strip())
        )

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
        self.atualizar_botao_transcrever(id_imagem)

        self.janela_principal.statusBar().showMessage(
            f"Transcrevendo imagem #{id_imagem} "
            f"da Nota {self.numero}..."
        )

        self.transcritor = TranscritorOCR(
            id_imagem,
            imagem,
            self,
        )

        self.transcritor.concluido.connect(
            self.transcricao_concluida
        )
        self.transcritor.erro.connect(
            self.transcricao_com_erro
        )
        self.transcritor.finished.connect(
            self.liberar_transcritor
        )

        self.transcritor.start()

    def transcricao_concluida(self, id_imagem, texto):
        self.editor.mostrar_texto(id_imagem, texto)
        self.finalizar_transcricao()

        self.janela_principal.statusBar().showMessage(
            f"Transcrição da imagem #{id_imagem} "
            f"da Nota {self.numero} concluída."
        )

    def transcricao_com_erro(self, id_imagem, mensagem):
        self.finalizar_transcricao()

        QMessageBox.critical(
            self,
            "Erro na transcrição",
            mensagem,
        )

        self.janela_principal.statusBar().showMessage(
            f"Falha ao transcrever a imagem #{id_imagem}."
        )

    def finalizar_transcricao(self):
        self.em_transcricao = False

        self.atualizar_botao_transcrever(
            self.editor.id_selecionado
        )

    def liberar_transcritor(self):
        trabalhador = self.sender()

        if trabalhador is self.transcritor:
            self.transcritor = None

        trabalhador.deleteLater()

    def copiar_texto(self):
        editor = self.editor.editor_texto
        cursor = editor.textCursor()

        if cursor.hasSelection():
            texto = cursor.selection().toPlainText()
        else:
            texto = editor.toPlainText()

        texto = texto.replace("\ufffc", "").strip()

        if not texto:
            return

        QApplication.clipboard().setText(texto)

        self.janela_principal.statusBar().showMessage(
            f"Texto da Nota {self.numero} copiado."
        )

    def abrir_imagens(self):
        caminhos, _ = QFileDialog.getOpenFileNames(
            self,
            "Abrir imagens",
            "",
            (
                "Imagens (*.png *.jpg *.jpeg *.bmp "
                "*.tif *.tiff *.webp)"
                ";;Todos os arquivos (*)"
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
                "Erro ao abrir imagens",
                "Não foi possível abrir:\n\n"
                + "\n".join(falhas),
            )

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
            editor.insertFromMimeData(
                QMimeData()
            ) if False else None

            if editor.bloco_contem_imagem(
                editor.textCursor().block()
            ):
                editor.pular_linha_da_imagem()

            editor.insertPlainText(texto)

            self.janela_principal.statusBar().showMessage(
                f"Conteúdo colado na Nota {self.numero}."
            )

    def fechar_nota(self):
        if (
            self.transcritor is not None
            and self.transcritor.isRunning()
        ):
            QMessageBox.information(
                self,
                "Transcrição em andamento",
                "Aguarde a conclusão da transcrição "
                "antes de fechar esta nota."
            )
            return

        self.janela_principal.remover_nota(self)


# ============================================================
# JANELA PRINCIPAL
# ============================================================


class JanelaPrincipal(QMainWindow):

    def __init__(self):
        super().__init__()

        self.notas = []
        self.nota_ativa = None
        self.proximo_numero_nota = 1

        self.setWindowTitle(TITULO_JANELA)
        self.resize(1200, 750)
        self.setMinimumSize(700, 450)

        self.criar_interface()
        self.configurar_atalhos()
        self.aplicar_estilo()

        self.adicionar_nota()

        self.statusBar().showMessage(
            "Pronto para transcrever."
        )

    def criar_interface(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        layout_principal = QVBoxLayout(central)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        # Cabeçalho
        cabecalho = QHBoxLayout()
        cabecalho.setContentsMargins(6, 4, 6, 4)
        cabecalho.setSpacing(4)

        self.titulo = QLabel("Transcrever imagem")
        self.titulo.setObjectName("titulo")

        self.botao_adicionar = QPushButton("+")
        self.botao_adicionar.setObjectName(
            "botaoAdicionarNota"
        )
        self.botao_adicionar.setFixedSize(40, 40)
        self.botao_adicionar.setToolTip("Adicionar nova nota")
        self.botao_adicionar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_adicionar.clicked.connect(
            self.adicionar_nota
        )

        cabecalho.addWidget(self.titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(self.botao_adicionar)

        layout_principal.addLayout(cabecalho)

        # Área horizontal das notas
        self.layout_notas = QHBoxLayout()
        self.layout_notas.setContentsMargins(0, 0, 0, 0)
        self.layout_notas.setSpacing(0)

        layout_principal.addLayout(
            self.layout_notas,
            stretch=1,
        )

    def adicionar_nota(self):
        nota = NotaWidget(
            self.proximo_numero_nota,
            self,
            self.centralWidget(),
        )

        self.proximo_numero_nota += 1

        self.notas.append(nota)
        self.nota_ativa = nota

        self.layout_notas.addWidget(
            nota,
            stretch=1,
        )

        nota.editor.editor_texto.setFocus()

        self.statusBar().showMessage(
            f"Nota {nota.numero} criada."
        )

    def remover_nota(self, nota):
        if nota not in self.notas:
            return

        self.layout_notas.removeWidget(nota)
        self.notas.remove(nota)

        nota.hide()
        nota.deleteLater()

        if self.nota_ativa is nota:
            self.nota_ativa = (
                self.notas[-1] if self.notas else None
            )

        if not self.notas:
            self.adicionar_nota()

        self.statusBar().showMessage(
            "Nota removida."
        )

    def configurar_atalhos(self):
        self.atalho_abrir = QShortcut(
            QKeySequence("Ctrl+O"),
            self,
        )
        self.atalho_abrir.activated.connect(
            self.abrir_imagens
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

            QLabel#tituloNota {
                color: #30343b;
                font-size: 14px;
                font-weight: bold;
            }

            QWidget#notaWidget {
                background-color: #ffffff;
                border: none;
                border-radius: 0;
            }

            QWidget#editorTranscricao {
                background-color: #ffffff;
                border: none;
                border-radius: 0;
            }

            QTextEdit#editorTexto {
                background-color: #ffffff;
                color: #202124;
                border: none;
                border-radius: 0;
                padding: 4px;
                font-size: 14px;
                selection-background-color: #cfe2ff;
            }

            QPushButton {
                background-color: #e8eaed;
                color: #202124;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
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
            }

            QPushButton#botaoTranscrever:hover {
                background-color: #0f57bd;
            }

            QPushButton#botaoTranscrever:disabled {
                background-color: #7da9e8;
                color: white;
            }

            QPushButton#botaoAdicionarNota {
                background-color: #1769e0;
                color: white;
                font-size: 24px;
                font-weight: bold;
                padding: 0;
            }

            QPushButton#botaoAdicionarNota:hover {
                background-color: #0f57bd;
            }

            QPushButton#botaoFecharNota {
                background-color: transparent;
                color: #70757a;
                font-size: 22px;
                padding: 0;
            }

            QPushButton#botaoFecharNota:hover {
                background-color: #dadde2;
                color: #202124;
            }
        """)

    def abrir_imagens(self):
        nota = self.nota_ativa

        if nota is None:
            return

        nota.abrir_imagens()

    def copiar_texto(self):
        nota = self.nota_ativa

        if nota is None:
            return

        nota.copiar_texto()

    def colar_conteudo(self):
        nota = self.nota_ativa

        if nota is None:
            return

        nota.colar_conteudo()

    def closeEvent(self, evento):
        em_execucao = [
            nota
            for nota in self.notas
            if (
                nota.transcritor is not None
                and nota.transcritor.isRunning()
            )
        ]

        if em_execucao:
            QMessageBox.information(
                self,
                "Transcrição em andamento",
                "Aguarde a conclusão de todas as transcrições "
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
