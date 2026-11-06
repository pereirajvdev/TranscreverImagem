"""TranscreverImagem: editor de notas com transcrição de imagens (OCR).

Atalhos:
    Ctrl+O             abrir imagens na nota ativa
    Ctrl+Shift+C       copiar o texto da nota ativa
    Ctrl+Shift+V       colagem especial (Paste from Sheet)
    Ctrl+Shift+T       alternar tema claro/escuro
    Ctrl+D             seleção múltipla no editor
    Ctrl + roda        zoom do editor

Notas:
    Arraste o cabeçalho de uma nota para reordená-la.
    Ao fechar uma nota com o mouse, o espaço dela é mantido até o
    cursor sair do botão X (as demais notas não se movem antes disso).
"""

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
    QByteArray,
    QIODevice,
    QMimeData,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QUrl,
    QSize,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QImage,
    QPainter,
    QPixmap,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
    QFont,
    QFontInfo,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from icones import criar_icone, criar_icone_carregando
from temas import (
    GerenciadorTemas,
    gerar_qss,
    montar_palette,
    repolir,
)
from colagem import DialogoColagemEspecial
from ordenacao import calcular_slot, indice_destino

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

# Zoom do editor (Ctrl + Scroll), em pontos.
ZOOM_MINIMO = 6.0
ZOOM_MAXIMO = 48.0
ZOOM_PASSO = 1.0

# Um "clique" da roda do mouse equivale a 120 unidades.
UNIDADES_POR_CLIQUE_RODA = 120

# Formato MIME do arraste de notas (carrega o número da nota).
MIME_NOTA = "application/x-transcreverimagem-nota"

# Acima deste número de colunas, a colagem de planilha pede confirmação.
LIMITE_CONFIRMAR_NOTAS = 10

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

        # --- Seleção múltipla (Ctrl+D) ---
        # Cursores secundários. O primário é sempre self.textCursor().
        self._multi_ativo = False
        self._cursores_extras = []
        self._texto_alvo = ""
        self._palavra_inteira = False
        # (início, fim) da palavra selecionada automaticamente no
        # primeiro Ctrl+D, para decidir se a busca usa "palavra inteira".
        self._selecao_automatica = None

        # Cores da seleção múltipla (definidas pelo tema da nota).
        self._cor_selecao_multipla = QColor(Qt.GlobalColor.lightGray)
        self._cor_cursor_multiplo = QColor(Qt.GlobalColor.black)

        # --- Zoom (Ctrl + Scroll), individual por editor ---
        # None = nenhum zoom aplicado ainda (vale a fonte do tema).
        self._zoom_pt = None
        self._acumulado_roda = 0

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
        self.cancelar_multipla()

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
        self.cancelar_multipla()

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
        self.cancelar_multipla()
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

    # --------------------------------------------------------
    # Texto puro e área de transferência
    # --------------------------------------------------------

    @staticmethod
    def _normalizar_busca(texto: str) -> str:
        """Representa o texto como toPlainText() o representa."""
        return (
            texto
            .replace("\u2029", "\n")
            .replace("\u2028", "\n")
            .replace("\u00a0", " ")
        )

    @classmethod
    def _para_texto_puro(cls, texto: str) -> str:
        """Texto como o usuário o vê: sem marcadores de imagem."""
        return cls._normalizar_busca(texto).replace("\ufffc", "")

    @staticmethod
    def _mime_somente_texto(texto: str) -> QMimeData:
        """QMimeData que carrega apenas text/plain."""
        mime = QMimeData()
        mime.setText(texto)
        return mime

    @classmethod
    def definir_area_de_transferencia(cls, texto: str):
        """Coloca SOMENTE texto puro na área de transferência."""
        QGuiApplication.clipboard().setMimeData(
            cls._mime_somente_texto(texto)
        )

    def _texto_puro_do_cursor(self, cursor: QTextCursor) -> str:
        return self._para_texto_puro(cursor.selectedText())

    def texto_para_copiar(self) -> str:
        """
        Texto puro para "Copiar texto": todas as seleções (modo
        múltiplo), a seleção atual ou, sem seleção, a nota inteira.
        """
        if self._multi_ativo:
            texto = self._texto_das_selecoes()

            if texto:
                return texto

        cursor = self.textCursor()

        if cursor.hasSelection():
            return self._texto_puro_do_cursor(cursor)

        return self._para_texto_puro(
            self.document().toPlainText()
        ).strip("\n")

    # --------------------------------------------------------
    # Seleção múltipla (Ctrl+D)
    # --------------------------------------------------------

    _TECLAS_MODIFICADORAS = (
        Qt.Key.Key_Shift,
        Qt.Key.Key_Control,
        Qt.Key.Key_Alt,
        Qt.Key.Key_AltGr,
        Qt.Key.Key_Meta,
        Qt.Key.Key_CapsLock,
        Qt.Key.Key_NumLock,
        Qt.Key.Key_ScrollLock,
    )

    _TECLAS_NAVEGACAO = (
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
    )

    def cancelar_multipla(self):
        """Sai do modo múltiplo, mantendo apenas o cursor primário."""
        if not self._multi_ativo and not self._cursores_extras:
            return

        self._multi_ativo = False
        self._cursores_extras = []
        self._texto_alvo = ""
        self._selecao_automatica = None

        self.setExtraSelections([])
        self.viewport().update()

    def aplicar_cores_multiplas(self, selecao: QColor, cursor: QColor):
        """Cores das seleções secundárias e dos carets extras."""
        self._cor_selecao_multipla = QColor(selecao)
        self._cor_cursor_multiplo = QColor(cursor)

        if self._multi_ativo:
            self._atualizar_destaques()
        else:
            self.viewport().update()

    def _atualizar_destaques(self):
        """Pinta as seleções secundárias (a primária é nativa)."""
        formato = QTextCharFormat()
        formato.setBackground(self._cor_selecao_multipla)

        selecoes = []

        for cursor in self._cursores_extras:
            if not cursor.hasSelection():
                continue

            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = formato
            selecoes.append(extra)

        self.setExtraSelections(selecoes)
        self.viewport().update()

    def _texto_das_selecoes(self):
        """Textos de todas as seleções, em ordem de aparição."""
        cursores = sorted(
            [*self._cursores_extras, self.textCursor()],
            key=lambda c: c.selectionStart(),
        )

        partes = (
            self._para_texto_puro(c.selectedText())
            for c in cursores
            if c.hasSelection()
        )

        return "\n".join(parte for parte in partes if parte)

    def _fundir_duplicados(self):
        """
        Funde cursores que passaram a se sobrepor (ou a ocupar a
        mesma posição). O resultado de uma fusão mantém a direção
        do cursor primário, se ele participou, e vira primário.
        Se nada precisar ser fundido, os cursores existentes são
        mantidos intactos (preserva a coluna desejada em Up/Down).
        """
        primario = self.textCursor()

        entradas = [
            (c.anchor(), c.position(), False)
            for c in self._cursores_extras
        ]
        entradas.append(
            (primario.anchor(), primario.position(), True)
        )

        entradas.sort(
            key=lambda e: (min(e[0], e[1]), max(e[0], e[1]))
        )

        fundidos = []

        for ancora, posicao, e_primario in entradas:
            inicio = min(ancora, posicao)
            fim = max(ancora, posicao)

            if fundidos:
                ultimo = fundidos[-1]
                u_inicio, u_fim = ultimo["inicio"], ultimo["fim"]

                sobrepoe = inicio < u_fim or (
                    inicio == u_fim
                    and (inicio == fim or u_inicio == u_fim)
                )

                if sobrepoe:
                    ultimo["fim"] = max(u_fim, fim)

                    if e_primario or not ultimo["primario"]:
                        # Direção do primário (ou do primeiro cursor).
                        if e_primario:
                            ultimo["direta"] = ancora <= posicao
                            ultimo["primario"] = True

                    continue

            fundidos.append({
                "inicio": inicio,
                "fim": fim,
                "direta": ancora <= posicao,
                "primario": e_primario,
            })

        # Nada fundido: mantém os objetos como estão.
        if len(fundidos) == len(entradas):
            return

        documento = self.document()
        novos = []
        novo_primario = None

        for item in fundidos:
            cursor = QTextCursor(documento)

            if item["direta"]:
                cursor.setPosition(item["inicio"])
                cursor.setPosition(
                    item["fim"], QTextCursor.MoveMode.KeepAnchor
                )
            else:
                cursor.setPosition(item["fim"])
                cursor.setPosition(
                    item["inicio"], QTextCursor.MoveMode.KeepAnchor
                )

            if item["primario"]:
                novo_primario = cursor
            else:
                novos.append(cursor)

        self._cursores_extras = novos

        if novo_primario is not None:
            self.setTextCursor(novo_primario)

        # Sobrou só o primário: volta ao modo convencional.
        if not novos:
            self.cancelar_multipla()

    @staticmethod
    def _e_caractere_de_palavra(c: str) -> bool:
        return c.isalnum() or c == "_"

    def _ocorrencia_toca_imagem(self, inicio: int, fim: int) -> bool:
        """True se o trecho (com \\n) atravessa um bloco com imagem."""
        documento = self.document()
        bloco = documento.findBlock(inicio)
        ultimo = documento.findBlock(fim)

        while bloco.isValid():
            if self.bloco_contem_imagem(bloco):
                return True

            if bloco == ultimo:
                break

            bloco = bloco.next()

        return False

    def _buscar_proxima_ocorrencia(self, texto, posicao, ocupados):
        """
        Procura `texto` (pode conter \\n) a partir de `posicao`, com
        retorno ao início. Ignora trechos sobrepostos a seleções
        existentes (`ocupados`: lista de (início, fim)) e trechos
        multilinha que tocam parágrafos com imagem.
        Retorna um QTextCursor com a ocorrência, ou None.
        """
        conteudo = self.document().toPlainText()
        multilinha = "\n" in texto
        tamanho = len(texto)

        for inicio_busca in (posicao, 0):
            i = conteudo.find(texto, inicio_busca)

            while i != -1:
                a, b = i, i + tamanho

                valido = not any(
                    a < fim and inicio < b
                    for inicio, fim in ocupados
                )

                if valido and self._palavra_inteira:
                    antes = a > 0 and self._e_caractere_de_palavra(
                        conteudo[a - 1]
                    )
                    depois = b < len(conteudo) and (
                        self._e_caractere_de_palavra(conteudo[b])
                    )
                    valido = not antes and not depois

                if valido and multilinha:
                    valido = not self._ocorrencia_toca_imagem(a, b)

                if valido:
                    cursor = QTextCursor(self.document())
                    cursor.setPosition(a)
                    cursor.setPosition(
                        b, QTextCursor.MoveMode.KeepAnchor
                    )
                    return cursor

                i = conteudo.find(texto, i + 1)

        return None

    def selecionar_proxima_ocorrencia(self):
        """Ctrl+D: adiciona a próxima ocorrência do texto selecionado."""
        cursor = self.textCursor()

        # Sem seleção (e fora do modo): seleciona a palavra sob o cursor.
        if not self._multi_ativo and not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            texto = cursor.selectedText()

            if (
                not texto.strip()
                or "\ufffc" in texto
                or "\u2029" in texto
            ):
                QApplication.beep()
                return

            self._selecao_automatica = (
                cursor.selectionStart(),
                cursor.selectionEnd(),
            )
            self.setTextCursor(cursor)
            return

        texto = cursor.selectedText()

        # Nunca captura imagens (\ufffc). Quebras de linha são aceitas.
        if not texto or "\ufffc" in texto:
            QApplication.beep()
            return

        if not self._multi_ativo:
            self._texto_alvo = self._normalizar_busca(texto)

            # Palavra escolhida pelo primeiro Ctrl+D: só palavras inteiras.
            self._palavra_inteira = (
                self._selecao_automatica == (
                    cursor.selectionStart(),
                    cursor.selectionEnd(),
                )
            )
        else:
            # Depois de navegar com Shift+setas, o primário pode ter
            # uma seleção diferente da original: ela vira o novo alvo.
            atual = self._normalizar_busca(texto)

            if atual != self._texto_alvo:
                self._texto_alvo = atual
                self._palavra_inteira = False

        ocupados = [
            (c.selectionStart(), c.selectionEnd())
            for c in (*self._cursores_extras, cursor)
        ]

        achado = self._buscar_proxima_ocorrencia(
            self._texto_alvo,
            cursor.selectionEnd(),
            ocupados,
        )

        # Nada novo (única ocorrência ou todas já selecionadas).
        if achado is None:
            QApplication.beep()
            return

        # O antigo primário vira secundário; o achado vira primário.
        self._cursores_extras.append(QTextCursor(cursor))
        self._multi_ativo = True

        self.setTextCursor(achado)
        self.ensureCursorVisible()
        self._atualizar_destaques()

    # --------------------------------------------------------
    # Proteção das imagens nas edições múltiplas
    # --------------------------------------------------------

    @staticmethod
    def _selecao_toca_imagem(cursor: QTextCursor) -> bool:
        return (
            cursor.hasSelection()
            and "\ufffc" in cursor.selectedText()
        )

    def _em_bloco_com_imagem(self, cursor: QTextCursor) -> bool:
        return self.bloco_contem_imagem(cursor.block())

    def _inserir_texto_seguro(self, cursor: QTextCursor, texto: str):
        """Insere texto, mas nunca sobre imagens nem no parágrafo delas."""
        if (
            self._selecao_toca_imagem(cursor)
            or self._em_bloco_com_imagem(cursor)
        ):
            return

        cursor.insertText(texto)

    def _inserir_bloco_seguro(self, cursor: QTextCursor):
        if (
            self._selecao_toca_imagem(cursor)
            or self._em_bloco_com_imagem(cursor)
        ):
            return

        cursor.insertBlock()

    def _remover_selecao_segura(self, cursor: QTextCursor):
        if self._selecao_toca_imagem(cursor):
            return

        cursor.removeSelectedText()

    def _executar_em_todos(self, operacao):
        """
        Aplica `operacao(cursor)` a todos os cursores, de trás para
        frente, em um único bloco de edição (um único Ctrl+Z).
        O QTextDocument reajusta os demais cursores a cada edição.
        """
        primario = QTextCursor(self.textCursor())
        todos = [*self._cursores_extras, primario]

        ordenados = sorted(
            todos,
            key=lambda c: c.selectionStart(),
            reverse=True,
        )

        primario.beginEditBlock()

        try:
            for cursor in ordenados:
                operacao(cursor)
        finally:
            primario.endEditBlock()

        self._cursores_extras = [
            c for c in todos if c is not primario
        ]

        self.setTextCursor(primario)
        self._fundir_duplicados()
        self._atualizar_destaques()
        self.ensureCursorVisible()

    def _apagaria_imagem(self, cursor, para_tras: bool) -> bool:
        """
        True se apagar um caractere (sem seleção) atingiria uma imagem,
        ou juntaria o bloco atual a um bloco que contém imagem.
        """
        documento = self.document()
        posicao = cursor.position()
        alvo = posicao - 1 if para_tras else posicao

        if alvo < 0 or alvo >= documento.characterCount() - 1:
            return True

        if documento.characterAt(alvo) == "\ufffc":
            return True

        if para_tras and cursor.atBlockStart():
            vizinho = cursor.block().previous()
        elif not para_tras and cursor.atBlockEnd():
            vizinho = cursor.block().next()
        else:
            return False

        return vizinho.isValid() and self.bloco_contem_imagem(vizinho)

    def _apagar(self, cursor, para_tras: bool):
        if cursor.hasSelection():
            self._remover_selecao_segura(cursor)
            return

        if self._apagaria_imagem(cursor, para_tras):
            return

        if para_tras:
            cursor.deletePreviousChar()
        else:
            cursor.deleteChar()

    # --------------------------------------------------------
    # Navegação simultânea (setas, Home, End)
    # --------------------------------------------------------

    @staticmethod
    def _mover_cursor(cursor, chave, estender: bool, por_palavra: bool):
        """Move UM cursor como o editor nativo (e o VS Code) faria."""
        operacao = QTextCursor.MoveOperation
        modo = (
            QTextCursor.MoveMode.KeepAnchor
            if estender
            else QTextCursor.MoveMode.MoveAnchor
        )

        if chave == Qt.Key.Key_Left:
            # Com seleção e sem Shift, recolhe para o início dela.
            if cursor.hasSelection() and not estender and not por_palavra:
                cursor.setPosition(cursor.selectionStart())
            else:
                cursor.movePosition(
                    operacao.PreviousWord if por_palavra
                    else operacao.Left,
                    modo,
                )

        elif chave == Qt.Key.Key_Right:
            if cursor.hasSelection() and not estender and not por_palavra:
                cursor.setPosition(cursor.selectionEnd())
            else:
                cursor.movePosition(
                    operacao.NextWord if por_palavra
                    else operacao.Right,
                    modo,
                )

        elif chave == Qt.Key.Key_Up:
            # Na primeira linha, vai ao início dela.
            if not cursor.movePosition(operacao.Up, modo):
                cursor.movePosition(operacao.StartOfLine, modo)

        elif chave == Qt.Key.Key_Down:
            # Na última linha, vai ao fim dela.
            if not cursor.movePosition(operacao.Down, modo):
                cursor.movePosition(operacao.EndOfLine, modo)

        elif chave == Qt.Key.Key_Home:
            cursor.movePosition(operacao.StartOfLine, modo)

        elif chave == Qt.Key.Key_End:
            cursor.movePosition(operacao.EndOfLine, modo)

    def _navegar_todos(self, chave, estender: bool, por_palavra: bool):
        """
        Move todos os cursores ao mesmo tempo. Cada um parte da sua
        própria posição, então as posições relativas são preservadas;
        cursores que se encontram (ou se sobrepõem) são fundidos.
        """
        primario = QTextCursor(self.textCursor())
        todos = [*self._cursores_extras, primario]

        for cursor in todos:
            self._mover_cursor(cursor, chave, estender, por_palavra)

        self._cursores_extras = [
            c for c in todos if c is not primario
        ]

        self.setTextCursor(primario)
        self._fundir_duplicados()
        self._atualizar_destaques()
        self.ensureCursorVisible()

    # --------------------------------------------------------
    # Teclado do modo múltiplo
    # --------------------------------------------------------

    def _tratar_tecla_multipla(self, evento) -> bool:
        """
        Processa teclas da seleção múltipla.
        Retorna True se o evento foi consumido.
        """
        chave = evento.key()
        mods = evento.modifiers()

        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Ctrl+D (funciona dentro e fora do modo múltiplo).
        if (
            mods == Qt.KeyboardModifier.ControlModifier
            and chave == Qt.Key.Key_D
        ):
            self.selecionar_proxima_ocorrencia()
            return True

        if not self._multi_ativo:
            return False

        # Ctrl ou Alt isolados são atalhos; Ctrl+Alt é o AltGr do Windows.
        atalho = (ctrl != alt) or meta

        if chave in self._TECLAS_MODIFICADORAS:
            return False

        if chave == Qt.Key.Key_Escape:
            self.cancelar_multipla()
            return True

        # Navegação: move todos os cursores, sem encerrar o modo.
        # Ctrl+←/→ andam por palavra; Alt/Meta e Ctrl+Home/End/↑/↓
        # seguem o fluxo normal (encerram o modo).
        if chave in self._TECLAS_NAVEGACAO:
            por_palavra = ctrl and chave in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
            )

            if not alt and not meta and (not ctrl or por_palavra):
                self._navegar_todos(chave, shift, por_palavra)
                return True

        if evento.matches(QKeySequence.StandardKey.Copy):
            texto = self._texto_das_selecoes()

            if texto:
                self.definir_area_de_transferencia(texto)

            return True

        if evento.matches(QKeySequence.StandardKey.Cut):
            texto = self._texto_das_selecoes()

            if texto:
                self.definir_area_de_transferencia(texto)
                self._executar_em_todos(
                    self._remover_selecao_segura
                )

            return True

        if evento.matches(QKeySequence.StandardKey.Paste):
            self.insertFromMimeData(
                QApplication.clipboard().mimeData()
            )
            return True

        if not atalho:
            if chave == Qt.Key.Key_Backspace:
                self._executar_em_todos(
                    lambda c: self._apagar(c, True)
                )
                return True

            if chave == Qt.Key.Key_Delete:
                self._executar_em_todos(
                    lambda c: self._apagar(c, False)
                )
                return True

            if chave in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._executar_em_todos(self._inserir_bloco_seguro)
                return True

            texto = evento.text()

            if texto and texto.isprintable():
                self._executar_em_todos(
                    lambda c: self._inserir_texto_seguro(c, texto)
                )
                return True

        # Qualquer outra tecla (Ctrl+Z, Ctrl+Y, Ctrl+A, Tab, PageUp...)
        # encerra o modo e segue o fluxo normal do editor.
        self.cancelar_multipla()
        return False

    def paintEvent(self, evento):
        super().paintEvent(evento)

        if not self._multi_ativo:
            return

        # Desenha o caret de cada cursor secundário (com ou sem
        # seleção); o do primário é desenhado pelo próprio Qt.
        pintor = QPainter(self.viewport())

        for cursor in self._cursores_extras:
            retangulo = self.cursorRect(cursor)

            pintor.fillRect(
                retangulo.x(),
                retangulo.y(),
                max(self.cursorWidth(), 1),
                retangulo.height(),
                self._cor_cursor_multiplo,
            )

        pintor.end()

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
        # Qualquer clique encerra a seleção múltipla.
        self.cancelar_multipla()

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
    # Zoom (Ctrl + Scroll)
    # --------------------------------------------------------
    #
    # O zoom altera (1) a fonte padrão do documento, que vale para
    # todo texto sem tamanho explícito, e (2) proporcionalmente, os
    # tamanhos explícitos (ex.: texto colado do Word/HTML). Só o
    # tamanho muda: negrito, itálico, cores etc. são preservados
    # (mergeCharFormat) e as imagens não são tocadas.

    def _tamanho_fonte_atual(self) -> float:
        if self._zoom_pt is not None:
            return self._zoom_pt

        fonte = self.document().defaultFont()
        tamanho = fonte.pointSizeF()

        if tamanho <= 0:
            tamanho = QFontInfo(fonte).pointSizeF()

        return tamanho if tamanho > 0 else 10.0

    def alterar_zoom(self, passos: int):
        """Aumenta (passos > 0) ou diminui (passos < 0) o zoom."""
        atual = self._tamanho_fonte_atual()

        novo = min(
            max(atual + passos * ZOOM_PASSO, ZOOM_MINIMO),
            ZOOM_MAXIMO,
        )

        if abs(novo - atual) < 0.01:
            return

        self._definir_tamanho_fonte(atual, novo)

    def _definir_tamanho_fonte(self, atual: float, novo: float):
        razao = novo / atual

        documento = self.document()
        fonte = documento.defaultFont()
        fonte.setPointSizeF(novo)
        documento.setDefaultFont(fonte)

        self._zoom_pt = novo
        self._escalar_tamanhos_explicitos(razao)

        self.viewport().update()

    def _escalar_tamanhos_explicitos(self, razao: float):
        """
        Multiplica por `razao` os tamanhos explícitos de fonte dos
        fragmentos (pt ou px), preservando as diferenças relativas.
        Só mexe no documento se houver tamanhos explícitos.
        """
        alteracoes = []
        bloco = self.document().begin()

        while bloco.isValid():
            for fragmento in self.fragmentos(bloco):
                formato = fragmento.charFormat()

                if formato.isImageFormat():
                    continue

                if formato.hasProperty(
                    QTextFormat.Property.FontPointSize
                ):
                    alteracoes.append((
                        fragmento.position(),
                        fragmento.length(),
                        "pt",
                        formato.fontPointSize(),
                    ))
                elif formato.hasProperty(
                    QTextFormat.Property.FontPixelSize
                ):
                    alteracoes.append((
                        fragmento.position(),
                        fragmento.length(),
                        "px",
                        formato.intProperty(
                            QTextFormat.Property.FontPixelSize
                        ),
                    ))

            bloco = bloco.next()

        if not alteracoes:
            return

        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()

        for posicao, tamanho, tipo, valor in alteracoes:
            cursor.setPosition(posicao)
            cursor.setPosition(
                posicao + tamanho,
                QTextCursor.MoveMode.KeepAnchor,
            )

            formato = QTextCharFormat()

            if tipo == "pt":
                formato.setFontPointSize(max(valor * razao, 1.0))
            else:
                formato.setProperty(
                    QTextFormat.Property.FontPixelSize,
                    max(round(valor * razao), 1),
                )

            cursor.mergeCharFormat(formato)

        cursor.endEditBlock()

    def _reaplicar_zoom_ao_documento(self):
        """Mantém o zoom se o Qt/tema redefinir a fonte do widget."""
        zoom = getattr(self, "_zoom_pt", None)

        if zoom is None:
            return

        fonte = self.document().defaultFont()

        if abs(fonte.pointSizeF() - zoom) > 0.01:
            fonte.setPointSizeF(zoom)
            self.document().setDefaultFont(fonte)

    def changeEvent(self, evento):
        super().changeEvent(evento)

        if evento.type() == QEvent.Type.FontChange:
            self._reaplicar_zoom_ao_documento()

    def wheelEvent(self, evento):
        if evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = evento.angleDelta().y()

            if delta:
                # Acumula para suportar mouses de alta resolução
                # e touchpads (deltas menores que 120).
                self._acumulado_roda += delta
                passos = int(
                    self._acumulado_roda / UNIDADES_POR_CLIQUE_RODA
                )

                if passos:
                    self._acumulado_roda -= (
                        passos * UNIDADES_POR_CLIQUE_RODA
                    )
                    self.alterar_zoom(passos)

            evento.accept()
            return

        self._acumulado_roda = 0
        super().wheelEvent(evento)

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
        # Seleção múltipla tem prioridade; fora do modo, o fluxo
        # abaixo permanece exatamente como era.
        if self._tratar_tecla_multipla(evento):
            return

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
    # Arraste de notas sobre o editor
    # --------------------------------------------------------
    #
    # O QTextEdit aceita drops por conta própria; para que o arraste
    # de uma nota continue funcionando por cima dele, os eventos com o
    # formato MIME_NOTA são repassados à AreaNotas.

    def _area_de_notas(self):
        pai = self.parentWidget()

        while pai is not None and not isinstance(pai, AreaNotas):
            pai = pai.parentWidget()

        return pai

    def _encaminhar_arraste_de_nota(self, evento, soltar=False) -> bool:
        if not evento.mimeData().hasFormat(MIME_NOTA):
            return False

        area = self._area_de_notas()

        if area is None:
            evento.ignore()
            return True

        ponto = self.viewport().mapTo(area, evento.position().toPoint())
        area.tratar_arraste(evento, ponto, soltar)
        return True

    def dragEnterEvent(self, evento):
        if not self._encaminhar_arraste_de_nota(evento):
            super().dragEnterEvent(evento)

    def dragMoveEvent(self, evento):
        if not self._encaminhar_arraste_de_nota(evento):
            super().dragMoveEvent(evento)

    def dropEvent(self, evento):
        if not self._encaminhar_arraste_de_nota(evento, soltar=True):
            super().dropEvent(evento)

    def dragLeaveEvent(self, evento):
        area = self._area_de_notas()

        if area is not None:
            area.ocultar_destino()

        super().dragLeaveEvent(evento)

    # --------------------------------------------------------
    # Planilhas (Excel, Calc, Google Sheets...)
    # --------------------------------------------------------

    _MARCAS_FORMATO_PLANILHA = ("biff", "xml spreadsheet", "csv")
    _MARCAS_HTML_PLANILHA = (
        "<table",
        "urn:schemas-microsoft-com:office:excel",
        "excel.sheet",
    )

    @classmethod
    def _e_planilha(cls, source: QMimeData) -> bool:
        """True se o conteúdo veio de células de uma planilha."""
        if not source.hasText():
            return False

        formatos = " ".join(source.formats()).lower()

        if any(m in formatos for m in cls._MARCAS_FORMATO_PLANILHA):
            return True

        if source.hasHtml():
            html = source.html().lower()
            return any(m in html for m in cls._MARCAS_HTML_PLANILHA)

        return False

    @staticmethod
    def _mime_texto_puro(source: QMimeData) -> QMimeData:
        """
        Novo QMimeData só com o text/plain (colunas em \\t, linhas
        em \\n), descartando HTML, imagem e formatos proprietários.
        """
        texto = (
            source.text()
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )

        mime = QMimeData()
        mime.setText(texto)
        return mime

    # --------------------------------------------------------
    # Área de transferência
    # --------------------------------------------------------

    def canInsertFromMimeData(self, source: QMimeData):
        return source.hasImage() or super().canInsertFromMimeData(
            source
        )

    def insertFromMimeData(self, source: QMimeData):
        # Células de planilha: o Excel publica também uma IMAGEM e um
        # HTML da tabela. Ficamos só com o texto puro (\t e \n), e o
        # restante do método passa a enxergar apenas texto.
        if self._e_planilha(source):
            source = self._mime_texto_puro(source)

        # Modo múltiplo: texto vai para todos os cursores.
        # Imagem encerra o modo e segue o fluxo normal.
        if self._multi_ativo:
            if source.hasText() and not source.hasImage():
                texto = source.text()

                if texto:
                    self._executar_em_todos(
                        lambda c: self._inserir_texto_seguro(c, texto)
                    )

                return

            self.cancelar_multipla()

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
        """
        Tudo o que o editor envia à área de transferência (Ctrl+C,
        Ctrl+X, menu de contexto, arrastar) passa por aqui. O
        resultado é SEMPRE texto puro, exceto quando só uma imagem
        está selecionada (aí vai a própria imagem).
        O documento em si não é alterado.
        """
        # Modo múltiplo: texto de todas as seleções, em ordem.
        if self._multi_ativo:
            texto = self._texto_das_selecoes()

            if texto:
                return self._mime_somente_texto(texto)

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

        # Demais casos: somente text/plain (sem HTML, fontes, cores,
        # imagens incorporadas ou formatos proprietários).
        return self._mime_somente_texto(
            self._texto_puro_do_cursor(cursor)
        )


class EditorTranscricao(QWidget):
    imagem_inserida = Signal(int)
    imagem_selecionada = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("editorTranscricao")

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

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
        self.editor_texto.document().setDocumentMargin(14)

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


class CabecalhoNota(QWidget):
    """Cabeçalho da nota; arrastá-lo inicia a reordenação."""

    arraste_solicitado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._origem_clique = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            self._origem_clique = evento.position().toPoint()
            evento.accept()
            return

        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento):
        if (
            self._origem_clique is not None
            and evento.buttons() & Qt.MouseButton.LeftButton
        ):
            deslocamento = (
                evento.position().toPoint() - self._origem_clique
            )

            if (
                deslocamento.manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._origem_clique = None
                self.arraste_solicitado.emit()
                return

        super().mouseMoveEvent(evento)

    def mouseReleaseEvent(self, evento):
        self._origem_clique = None
        super().mouseReleaseEvent(evento)


class VagaNota(QWidget):
    """Espaço reservado no lugar de uma nota recém-fechada.

    Mantém a largura da nota (mesmo stretch no layout) para que as
    demais não mudem de tamanho nem de posição enquanto o cursor
    estiver sobre a região do botão X. Quando o cursor sai dessa
    região (ou da vaga), emite `liberada` uma única vez.
    """

    liberada = Signal()

    def __init__(self, dist_direita, topo, largura, altura, parent=None):
        super().__init__(parent)

        self._dist_direita = dist_direita
        self._topo = topo
        self._largura = largura
        self._altura = altura
        self._liberada = False

        self.setObjectName("vagaNota")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

    def zona_botao(self) -> QRect:
        """Onde o botão X estava, em coordenadas desta vaga."""
        return QRect(
            self.width() - self._dist_direita - self._largura,
            self._topo,
            self._largura,
            self._altura,
        )

    def _liberar(self):
        if not self._liberada:
            self._liberada = True
            self.liberada.emit()

    def mouseMoveEvent(self, evento):
        if not self.zona_botao().contains(evento.position().toPoint()):
            self._liberar()

        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento):
        self._liberar()
        super().leaveEvent(evento)


class AreaNotas(QWidget):
    """Contêiner horizontal das notas; aceita soltar notas arrastadas."""

    # (número da nota arrastada, slot de inserção)
    nota_solta = Signal(int, int)

    _LARGURA_INDICADOR = 4

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("areaNotas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        self._fonte_notas = lambda: []

        # Barra que marca onde a nota será inserida.
        self.indicador = QWidget(self)
        self.indicador.setObjectName("indicadorInsercao")
        self.indicador.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self.indicador.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.indicador.hide()

    def definir_fonte_notas(self, fonte):
        """`fonte()` devolve as notas na ordem visual."""
        self._fonte_notas = fonte

    def _numero_valido(self, mime):
        if not mime.hasFormat(MIME_NOTA):
            return None

        try:
            numero = int(bytes(mime.data(MIME_NOTA)).decode())
        except ValueError:
            return None

        existe = any(n.numero == numero for n in self._fonte_notas())
        return numero if existe else None

    def slot_em(self, x: int) -> int:
        centros = [
            nota.geometry().center().x() for nota in self._fonte_notas()
        ]
        return calcular_slot(centros, x)

    def mostrar_destino(self, slot: int):
        notas = self._fonte_notas()

        if not notas:
            self.ocultar_destino()
            return

        if slot <= 0:
            x = notas[0].geometry().left()
        elif slot >= len(notas):
            x = notas[-1].geometry().right() + 1
        else:
            x = (
                notas[slot - 1].geometry().right()
                + 1
                + notas[slot].geometry().left()
            ) // 2

        largura = self._LARGURA_INDICADOR
        esquerda = min(max(x - largura // 2, 0), self.width() - largura)

        self.indicador.setGeometry(esquerda, 0, largura, self.height())
        self.indicador.show()
        self.indicador.raise_()

    def ocultar_destino(self):
        self.indicador.hide()

    def tratar_arraste(self, evento, ponto, soltar=False):
        """Entrada comum dos eventos de arraste (da área ou do editor)."""
        numero = self._numero_valido(evento.mimeData())

        if numero is None:
            self.ocultar_destino()
            evento.ignore()
            return

        slot = self.slot_em(ponto.x())

        evento.setDropAction(Qt.DropAction.MoveAction)
        evento.accept()

        if soltar:
            self.ocultar_destino()
            self.nota_solta.emit(numero, slot)
        else:
            self.mostrar_destino(slot)

    def dragEnterEvent(self, evento):
        self.tratar_arraste(evento, evento.position().toPoint())

    def dragMoveEvent(self, evento):
        self.tratar_arraste(evento, evento.position().toPoint())

    def dragLeaveEvent(self, evento):
        self.ocultar_destino()

    def dropEvent(self, evento):
        self.tratar_arraste(
            evento, evento.position().toPoint(), soltar=True
        )


class NotaWidget(QWidget):

    def __init__(self, numero: int, janela_principal, parent=None):
        super().__init__(parent)

        self.numero = numero
        self.janela_principal = janela_principal
        self.transcritor = None
        self.em_transcricao = False

        self._paleta = janela_principal.temas.paleta
        self._icone_transcrever = None
        self._angulo_spinner = 0

        self._timer_spinner = QTimer(self)
        self._timer_spinner.setInterval(60)
        self._timer_spinner.timeout.connect(self._girar_spinner)

        self.setObjectName("notaWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.criar_interface()

    def criar_interface(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Cabeçalho da nota
        self.cabecalho_nota = CabecalhoNota(self)
        self.cabecalho_nota.setObjectName("cabecalhoNota")
        self.cabecalho_nota.setToolTip("Arraste para reordenar")
        self.cabecalho_nota.arraste_solicitado.connect(
            self._iniciar_arraste
        )
        self.cabecalho_nota.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self.cabecalho_nota.setProperty("ativa", False)

        cabecalho = QHBoxLayout(self.cabecalho_nota)
        cabecalho.setContentsMargins(12, 6, 8, 6)
        cabecalho.setSpacing(6)

        self.titulo = QLabel(f"Nota {self.numero}")
        self.titulo.setObjectName("tituloNota")
        self.titulo.setProperty("ativa", False)

        self.botao_fechar = QPushButton()
        self.botao_fechar.setObjectName("botaoFecharNota")
        self.botao_fechar.setProperty("papel", "fechar")
        self.botao_fechar.setFixedSize(26, 26)
        self.botao_fechar.setIconSize(QSize(14, 14))
        self.botao_fechar.setToolTip("Fechar nota")
        self.botao_fechar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_fechar.setFocusPolicy(
            Qt.FocusPolicy.TabFocus
        )
        self.botao_fechar.clicked.connect(
            self.fechar_nota
        )

        cabecalho.addWidget(self.titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(self.botao_fechar)

        layout.addWidget(self.cabecalho_nota)

        # Editor: ocupa todo o espaço vertical disponível
        self.editor = EditorTranscricao(self)
        layout.addWidget(self.editor, stretch=1)

        # Barra de ações (só aparece quando há algum botão visível)
        self.barra_acoes = QWidget(self)
        self.barra_acoes.setObjectName("barraAcoes")
        self.barra_acoes.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )

        layout_botoes = QHBoxLayout(self.barra_acoes)
        layout_botoes.setContentsMargins(10, 8, 10, 8)
        layout_botoes.setSpacing(8)

        self.botao_transcrever = QPushButton("Transcrever")
        self.botao_transcrever.setObjectName("botaoTranscrever")
        self.botao_transcrever.setProperty("papel", "primario")
        self.botao_transcrever.setIconSize(QSize(16, 16))
        self.botao_transcrever.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_transcrever.setFocusPolicy(
            Qt.FocusPolicy.TabFocus
        )
        self.botao_transcrever.hide()
        self.botao_transcrever.clicked.connect(
            self.transcrever_imagem
        )

        self.botao_copiar = QPushButton("Copiar texto")
        self.botao_copiar.setObjectName("botaoCopiar")
        self.botao_copiar.setIconSize(QSize(16, 16))
        self.botao_copiar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_copiar.setFocusPolicy(
            Qt.FocusPolicy.TabFocus
        )
        self.botao_copiar.hide()
        self.botao_copiar.clicked.connect(
            self.copiar_texto
        )

        layout_botoes.addWidget(self.botao_transcrever)
        layout_botoes.addStretch()
        layout_botoes.addWidget(self.botao_copiar)

        layout.addWidget(self.barra_acoes)

        # Eventos do editor
        self.editor.imagem_selecionada.connect(
            self.atualizar_botao_transcrever
        )

        self.editor.editor_texto.textChanged.connect(
            self.atualizar_botao_copiar
        )

        # Registrar a nota ativa ao receber foco
        self.editor.editor_texto.focusInEvent = (
            self._criar_focus_handler(
                self.editor.editor_texto.focusInEvent
            )
        )

        self.aplicar_tema(self._paleta)
        self._atualizar_barra_acoes()

    def _criar_focus_handler(self, handler_original):
        def handler(evento):
            self.janela_principal.nota_ativa = self
            handler_original(evento)

        return handler

    def aplicar_tema(self, paleta):
        """Atualiza ícones e cores do editor. Não toca no conteúdo."""
        self._paleta = paleta

        self.botao_fechar.setIcon(
            criar_icone("fechar", paleta.texto_suave)
        )
        self.botao_copiar.setIcon(
            criar_icone(
                "copiar",
                paleta.texto,
                cor_desativada=paleta.texto_desativado,
            )
        )

        self._icone_transcrever = criar_icone(
            "transcrever", paleta.texto_sobre_destaque
        )

        if not self.em_transcricao:
            self.botao_transcrever.setIcon(self._icone_transcrever)

        self.editor.editor_texto.aplicar_cores_multiplas(
            QColor(paleta.selecao_secundaria),
            QColor(paleta.cursor_secundario),
        )

    def definir_ativa(self, ativa: bool):
        """Destaca o cabeçalho da nota que está em uso."""
        if bool(self.cabecalho_nota.property("ativa")) == ativa:
            return

        for widget in (self.cabecalho_nota, self.titulo):
            widget.setProperty("ativa", ativa)
            repolir(widget)

    def _atualizar_barra_acoes(self):
        visivel = (
            self.botao_transcrever.isVisibleTo(self.barra_acoes)
            or self.botao_copiar.isVisibleTo(self.barra_acoes)
        )
        self.barra_acoes.setVisible(visivel)

    def _iniciar_spinner(self):
        self._angulo_spinner = 0
        self._girar_spinner()
        self._timer_spinner.start()

    def _parar_spinner(self):
        self._timer_spinner.stop()

    def _girar_spinner(self):
        self._angulo_spinner = (self._angulo_spinner + 30) % 360

        self.botao_transcrever.setIcon(
            criar_icone_carregando(
                self._paleta.texto_sobre_destaque,
                self._angulo_spinner,
                tamanho=16,
            )
        )

    def atualizar_botao_transcrever(self, id_imagem):
        if id_imagem == SEM_IMAGEM:
            self.botao_transcrever.hide()
            self._atualizar_barra_acoes()
            return

        if self.em_transcricao:
            self.botao_transcrever.setText("Transcrevendo...")
            self.botao_transcrever.setEnabled(False)
        else:
            self.botao_transcrever.setText(
                f"Transcrever imagem #{id_imagem}"
            )
            self.botao_transcrever.setIcon(self._icone_transcrever)
            self.botao_transcrever.setEnabled(True)

        self.botao_transcrever.show()
        self._atualizar_barra_acoes()

    def atualizar_botao_copiar(self):
        texto = (
            self.editor.editor_texto
            .toPlainText()
            .replace("\ufffc", "")
        )

        self.botao_copiar.setVisible(
            bool(texto.strip())
        )
        self._atualizar_barra_acoes()

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

        self._iniciar_spinner()

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
        self._parar_spinner()

        self.atualizar_botao_transcrever(
            self.editor.id_selecionado
        )

    def liberar_transcritor(self):
        trabalhador = self.sender()

        if trabalhador is self.transcritor:
            self.transcritor = None

        trabalhador.deleteLater()

    def copiar_texto(self):
        """
        Copia SOMENTE texto puro: todas as seleções (Ctrl+D), a
        seleção atual ou, sem seleção, o conteúdo inteiro da nota.
        """
        editor = self.editor.editor_texto
        texto = editor.texto_para_copiar()

        if not texto.strip():
            return

        editor.definir_area_de_transferencia(texto)

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

            if editor.bloco_contem_imagem(
                editor.textCursor().block()
            ):
                editor.pular_linha_da_imagem()

            editor.insertPlainText(texto)

            self.janela_principal.statusBar().showMessage(
                f"Conteúdo colado na Nota {self.numero}."
            )

    def zona_botao_fechar(self):
        """(distância à borda direita, topo, largura, altura) do X."""
        canto = self.botao_fechar.mapTo(self, QPoint(0, 0))
        largura = self.botao_fechar.width()

        return (
            self.width() - canto.x() - largura,
            canto.y(),
            largura,
            self.botao_fechar.height(),
        )

    def _iniciar_arraste(self):
        """Inicia o arraste desta nota (QDrag nativo do Qt)."""
        self.janela_principal.preparar_arraste()

        # Miniatura translúcida da nota, presa pelo topo.
        miniatura = self.grab().scaledToWidth(
            min(240, max(self.width(), 1)),
            Qt.TransformationMode.SmoothTransformation,
        )
        translucida = QPixmap(miniatura.size())
        translucida.fill(Qt.GlobalColor.transparent)

        pintor = QPainter(translucida)
        pintor.setOpacity(0.8)
        pintor.drawPixmap(0, 0, miniatura)
        pintor.end()

        mime = QMimeData()
        mime.setData(MIME_NOTA, QByteArray(str(self.numero).encode()))

        arraste = QDrag(self.cabecalho_nota)
        arraste.setMimeData(mime)
        arraste.setPixmap(translucida)
        arraste.setHotSpot(QPoint(translucida.width() // 2, 14))

        # A nota de origem fica esmaecida enquanto é arrastada.
        efeito = QGraphicsOpacityEffect(self)
        efeito.setOpacity(0.45)
        self.setGraphicsEffect(efeito)

        try:
            arraste.exec(Qt.DropAction.MoveAction)
        finally:
            self.setGraphicsEffect(None)
            self.janela_principal.finalizar_arraste()

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
        self._nota_ativa = None
        self.proximo_numero_nota = 1
        self._vagas = []

        self.temas = GerenciadorTemas(self)
        self.temas.tema_alterado.connect(self.aplicar_tema)

        self.setWindowTitle(TITULO_JANELA)
        self.resize(1200, 750)
        self.setMinimumSize(700, 450)

        self.criar_interface()
        self.configurar_atalhos()
        self.aplicar_tema()

        self.adicionar_nota()

        self.statusBar().showMessage(
            "Pronto para transcrever."
        )

    @property
    def nota_ativa(self):
        return self._nota_ativa

    @nota_ativa.setter
    def nota_ativa(self, nota):
        self._nota_ativa = nota

        for outra in self.notas:
            outra.definir_ativa(outra is nota)

    def criar_interface(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        layout_principal = QVBoxLayout(central)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        # Cabeçalho
        self.cabecalho = QWidget(central)
        self.cabecalho.setObjectName("cabecalhoPrincipal")
        self.cabecalho.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )

        cabecalho = QHBoxLayout(self.cabecalho)
        cabecalho.setContentsMargins(14, 10, 14, 10)
        cabecalho.setSpacing(10)

        self.logo = QLabel()
        self.logo.setFixedSize(28, 28)

        self.titulo = QLabel("Transcrever imagem")
        self.titulo.setObjectName("titulo")

        self.botao_tema = QPushButton()
        self.botao_tema.setObjectName("botaoTema")
        self.botao_tema.setProperty("papel", "icone")
        self.botao_tema.setFixedSize(36, 36)
        self.botao_tema.setIconSize(QSize(20, 20))
        self.botao_tema.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_tema.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.botao_tema.clicked.connect(self.alternar_tema)

        self.botao_adicionar = QPushButton()
        self.botao_adicionar.setObjectName("botaoAdicionarNota")
        self.botao_adicionar.setProperty("papel", "primario-icone")
        self.botao_adicionar.setFixedSize(36, 36)
        self.botao_adicionar.setIconSize(QSize(18, 18))
        self.botao_adicionar.setToolTip("Adicionar nova nota")
        self.botao_adicionar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.botao_adicionar.setFocusPolicy(
            Qt.FocusPolicy.TabFocus
        )
        self.botao_adicionar.clicked.connect(
            self.adicionar_nota
        )

        cabecalho.addWidget(self.logo)
        cabecalho.addWidget(self.titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(self.botao_tema)
        cabecalho.addWidget(self.botao_adicionar)

        layout_principal.addWidget(self.cabecalho)

        # Área horizontal das notas: o fundo é a cor da borda e o
        # espaçamento de 1 px vira o divisor entre os painéis.
        self.area_notas = AreaNotas(central)
        self.area_notas.definir_fonte_notas(lambda: self.notas)
        self.area_notas.nota_solta.connect(self.mover_nota)

        self.layout_notas = QHBoxLayout(self.area_notas)
        self.layout_notas.setContentsMargins(0, 0, 0, 0)
        self.layout_notas.setSpacing(1)

        layout_principal.addWidget(
            self.area_notas,
            stretch=1,
        )

        self.statusBar().setSizeGripEnabled(False)

    # --------------------------------------------------------
    # Criação, fechamento e ordem das notas
    # --------------------------------------------------------
    #
    # `self.notas` é a única fonte de verdade da ordem; o layout é
    # sempre reflexo dela. As notas são identificadas por `numero`
    # (estável, nunca reaproveitado), jamais pela posição.

    def criar_nota(self, indice=None, texto=None):
        """Cria uma nota na posição `indice` (padrão: no fim)."""
        self._colapsar_vagas()

        if indice is None or not 0 <= indice <= len(self.notas):
            indice = len(self.notas)

        nota = NotaWidget(
            self.proximo_numero_nota,
            self,
            self.centralWidget(),
        )

        self.proximo_numero_nota += 1

        self.notas.insert(indice, nota)
        self.layout_notas.insertWidget(indice, nota, stretch=1)

        if texto:
            editor = nota.editor.editor_texto
            editor.setPlainText(texto)
            editor.document().clearUndoRedoStacks()

        return nota

    def adicionar_nota(self):
        nota = self.criar_nota()
        self.nota_ativa = nota

        nota.editor.editor_texto.setFocus()

        self.statusBar().showMessage(
            f"Nota {nota.numero} criada."
        )

    def remover_nota(self, nota, manter_vaga=None):
        """Fecha a nota.

        Se o cursor está sobre o botão X, o espaço dela é mantido
        (VagaNota) até o cursor sair dali. `manter_vaga` força o
        comportamento (útil em testes); None detecta pelo mouse.
        """
        if nota not in self.notas:
            return

        self._colapsar_vagas()

        if manter_vaga is None:
            manter_vaga = nota.botao_fechar.underMouse()

        manter_vaga = manter_vaga and len(self.notas) > 1

        indice = self.layout_notas.indexOf(nota)
        zona = nota.zona_botao_fechar()

        self.layout_notas.removeWidget(nota)
        self.notas.remove(nota)

        nota.hide()
        nota.deleteLater()

        if manter_vaga:
            vaga = VagaNota(*zona, parent=self.area_notas)
            vaga.liberada.connect(
                lambda v=vaga: self._colapsar_vaga(v)
            )

            self._vagas.append(vaga)
            self.layout_notas.insertWidget(indice, vaga, stretch=1)

        if self.nota_ativa is nota:
            self.nota_ativa = (
                self.notas[-1] if self.notas else None
            )

        if not self.notas:
            self.adicionar_nota()

        self.statusBar().showMessage(
            "Nota removida."
        )

    def _colapsar_vaga(self, vaga):
        """Libera o espaço reservado; o layout recalcula as notas."""
        if vaga not in self._vagas:
            return

        self._vagas.remove(vaga)
        self.layout_notas.removeWidget(vaga)

        vaga.hide()
        vaga.deleteLater()

    def _colapsar_vagas(self):
        for vaga in list(self._vagas):
            self._colapsar_vaga(vaga)

    def preparar_arraste(self):
        # A ordem visual precisa ser igual à ordem dos dados.
        self._colapsar_vagas()

    def finalizar_arraste(self):
        self.area_notas.ocultar_destino()

    def mover_nota(self, numero: int, slot: int) -> bool:
        """Move a nota `numero` para o `slot` de inserção informado."""
        self._colapsar_vagas()

        origem = next(
            (i for i, n in enumerate(self.notas) if n.numero == numero),
            None,
        )

        if origem is None:
            return False

        destino = indice_destino(origem, slot)

        if destino == origem:
            return False

        nota = self.notas.pop(origem)
        self.notas.insert(destino, nota)

        self.setUpdatesEnabled(False)

        try:
            self.layout_notas.removeWidget(nota)
            self.layout_notas.insertWidget(destino, nota, stretch=1)
        finally:
            self.setUpdatesEnabled(True)

        self.statusBar().showMessage(
            f"Nota {numero} movida para a posição {destino + 1}."
        )

        return True

    # --------------------------------------------------------
    # Colagem especial
    # --------------------------------------------------------

    def abrir_colagem_especial(self):
        dialogo = DialogoColagemEspecial(
            QGuiApplication.clipboard().text(),
            self.temas.paleta,
            self,
        )
        dialogo.exec()

        if dialogo.opcao_escolhida == DialogoColagemEspecial.PASTE_FROM_SHEET:
            self.colar_de_planilha(dialogo.colunas)

    def colar_de_planilha(self, colunas):
        """Cria uma nota por coluna, logo após a nota ativa."""
        if not colunas:
            self.statusBar().showMessage(
                "Nenhum dado tabular para colar."
            )
            return

        if len(colunas) > LIMITE_CONFIRMAR_NOTAS:
            resposta = QMessageBox.question(
                self,
                "Paste from Sheet",
                f"Serão criadas {len(colunas)} notas. "
                "Deseja continuar?",
            )

            if resposta != QMessageBox.StandardButton.Yes:
                return

        self._colapsar_vagas()

        if self.nota_ativa in self.notas:
            base = self.notas.index(self.nota_ativa) + 1
        else:
            base = len(self.notas)

        novas = []

        self.setUpdatesEnabled(False)

        try:
            for deslocamento, texto in enumerate(colunas):
                novas.append(
                    self.criar_nota(base + deslocamento, texto)
                )
        finally:
            self.setUpdatesEnabled(True)

        self.nota_ativa = novas[0]
        novas[0].editor.editor_texto.setFocus()

        self.statusBar().showMessage(
            f"{len(novas)} nota(s) criada(s) a partir da planilha."
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

        self.atalho_tema = QShortcut(
            QKeySequence("Ctrl+Shift+T"),
            self,
        )
        self.atalho_tema.activated.connect(self.alternar_tema)

        self.atalho_colagem_especial = QShortcut(
            QKeySequence("Ctrl+Shift+V"),
            self,
        )
        self.atalho_colagem_especial.activated.connect(
            self.abrir_colagem_especial
        )

    def alternar_tema(self):
        self.temas.alternar()

    def aplicar_tema(self, *_):
        paleta = self.temas.paleta
        escuro = self.temas.escuro
        app = QApplication.instance()

        # Opcional (PySide6 >= 6.8): faz a barra de título do Windows
        # acompanhar o tema.
        dicas = QGuiApplication.styleHints()

        if hasattr(dicas, "setColorScheme"):
            dicas.setColorScheme(
                Qt.ColorScheme.Dark if escuro
                else Qt.ColorScheme.Light
            )

        app.setPalette(montar_palette(paleta))
        app.setStyleSheet(gerar_qss(paleta))

        self.logo.setPixmap(
            criar_icone("logo", paleta.destaque).pixmap(28, 28)
        )
        self.botao_tema.setIcon(
            criar_icone(
                "sol" if escuro else "lua",
                paleta.texto_suave,
            )
        )
        self.botao_tema.setToolTip(
            "Mudar para o tema claro" if escuro
            else "Mudar para o tema escuro"
        )
        self.botao_adicionar.setIcon(
            criar_icone("mais", paleta.texto_sobre_destaque)
        )

        for nota in self.notas:
            nota.aplicar_tema(paleta)

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
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))

    janela = JanelaPrincipal()
    janela.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()