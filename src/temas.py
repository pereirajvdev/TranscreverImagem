from dataclasses import asdict, dataclass
from string import Template

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QPalette


ORGANIZACAO = "TranscreverImagem"
APLICACAO = "TranscreverImagem"
CHAVE_TEMA = "interface/tema"
TEMA_PADRAO = "claro"


@dataclass(frozen=True)
class Paleta:
    nome: str

    # Superfícies
    janela: str
    painel: str
    cabecalho: str
    borda: str

    # Texto
    texto: str
    texto_suave: str
    texto_desativado: str

    # Destaque
    destaque: str
    destaque_hover: str
    destaque_pressionado: str
    destaque_desativado: str
    texto_sobre_destaque: str

    # Botões neutros
    botao: str
    botao_hover: str
    botao_pressionado: str
    perigo_fundo: str

    # Editor
    editor_fundo: str
    editor_texto: str
    placeholder: str
    selecao: str
    selecao_secundaria: str
    cursor_secundario: str

    # Barras de rolagem
    rolagem: str
    rolagem_hover: str


TEMA_CLARO = Paleta(
    nome="claro",
    janela="#F3F4F6",
    painel="#FFFFFF",
    cabecalho="#FFFFFF",
    borda="#E2E5E9",
    texto="#1F2328",
    texto_suave="#6B7280",
    texto_desativado="#A1A8B3",
    destaque="#2563EB",
    destaque_hover="#1D4ED8",
    destaque_pressionado="#1E40AF",
    destaque_desativado="#93B4F5",
    texto_sobre_destaque="#FFFFFF",
    botao="#EEF0F3",
    botao_hover="#E3E6EB",
    botao_pressionado="#D7DBE1",
    perigo_fundo="#FDE2E2",
    editor_fundo="#FFFFFF",
    editor_texto="#1F2328",
    placeholder="#9AA1AC",
    selecao="#B4D2FE",
    selecao_secundaria="#DCEAFE",
    cursor_secundario="#1F2328",
    rolagem="#CDD2D9",
    rolagem_hover="#B3BAC4",
)

TEMA_ESCURO = Paleta(
    nome="escuro",
    janela="#17191C",
    painel="#202327",
    cabecalho="#202327",
    borda="#33373D",
    texto="#E6E8EB",
    texto_suave="#9AA1AB",
    texto_desativado="#6A717B",
    destaque="#3B82F6",
    destaque_hover="#5B9BF8",
    destaque_pressionado="#2F6FDB",
    destaque_desativado="#2E4A78",
    texto_sobre_destaque="#FFFFFF",
    botao="#2B2F34",
    botao_hover="#353A41",
    botao_pressionado="#3F454D",
    perigo_fundo="#4A2528",
    editor_fundo="#1C1E22",
    editor_texto="#DDE1E6",
    placeholder="#6A717B",
    selecao="#2D5A94",
    selecao_secundaria="#223F63",
    cursor_secundario="#DDE1E6",
    rolagem="#3A3F46",
    rolagem_hover="#4A5058",
)

PALETAS = {
    TEMA_CLARO.nome: TEMA_CLARO,
    TEMA_ESCURO.nome: TEMA_ESCURO,
}


class GerenciadorTemas(QObject):
    """Guarda o tema atual, persiste a escolha e avisa quando muda."""

    tema_alterado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config = QSettings(ORGANIZACAO, APLICACAO)

        nome = self._config.value(CHAVE_TEMA, TEMA_PADRAO, type=str)
        self._nome = nome if nome in PALETAS else TEMA_PADRAO

    @property
    def nome(self) -> str:
        return self._nome

    @property
    def paleta(self) -> Paleta:
        return PALETAS[self._nome]

    @property
    def escuro(self) -> bool:
        return self._nome == TEMA_ESCURO.nome

    def definir(self, nome: str):
        if nome not in PALETAS or nome == self._nome:
            return

        self._nome = nome
        self._config.setValue(CHAVE_TEMA, nome)
        self.tema_alterado.emit(nome)

    def alternar(self):
        self.definir(
            TEMA_CLARO.nome if self.escuro else TEMA_ESCURO.nome
        )


def repolir(widget):
    """Reaplica o QSS depois de mudar uma propriedade dinâmica."""
    estilo = widget.style()
    estilo.unpolish(widget)
    estilo.polish(widget)
    widget.update()


def montar_palette(p: Paleta) -> QPalette:
    papel = QPalette.ColorRole
    palette = QPalette()

    cores = {
        papel.Window: p.janela,
        papel.WindowText: p.texto,
        papel.Base: p.editor_fundo,
        papel.AlternateBase: p.painel,
        papel.Text: p.texto,
        papel.Button: p.botao,
        papel.ButtonText: p.texto,
        papel.ToolTipBase: p.painel,
        papel.ToolTipText: p.texto,
        papel.PlaceholderText: p.placeholder,
        papel.Highlight: p.selecao,
        papel.HighlightedText: p.texto,
        papel.Link: p.destaque,
    }

    for chave, cor in cores.items():
        palette.setColor(chave, QColor(cor))

    for chave in (papel.WindowText, papel.Text, papel.ButtonText):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            chave,
            QColor(p.texto_desativado),
        )

    return palette


_MODELO_QSS = Template("""
QMainWindow, QDialog, QMessageBox {
    background-color: $janela;
}

QLabel {
    color: $texto;
    background: transparent;
}

/* ---------- Cabeçalho principal ---------- */

QWidget#cabecalhoPrincipal {
    background-color: $cabecalho;
    border-bottom: 1px solid $borda;
}

QLabel#titulo {
    font-size: 15px;
    font-weight: 600;
}

/* ---------- Notas ---------- */

QWidget#areaNotas {
    background-color: $borda;
}

QWidget#notaWidget {
    background-color: $painel;
}

QWidget#cabecalhoNota {
    background-color: transparent;
    border-top: 2px solid transparent;
}

QWidget#cabecalhoNota[ativa="true"] {
    border-top: 2px solid $destaque;
}

QLabel#tituloNota {
    color: $texto_suave;
    font-size: 12px;
    font-weight: 600;
}

QLabel#tituloNota[ativa="true"] {
    color: $destaque;
}

QWidget#barraAcoes {
    background-color: $painel;
    border-top: 1px solid $borda;
}

/* ---------- Editor ---------- */

QWidget#editorTranscricao {
    background-color: $editor_fundo;
}

QTextEdit#editorTexto {
    background-color: $editor_fundo;
    color: $editor_texto;
    border: none;
    padding: 4px 6px;
    font-size: 11pt;
    selection-background-color: $selecao;
    selection-color: $editor_texto;
}

/* ---------- Botões ---------- */

QPushButton {
    background-color: $botao;
    color: $texto;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: $botao_hover;
}

QPushButton:pressed {
    background-color: $botao_pressionado;
}

QPushButton:focus {
    border: 1px solid $destaque;
}

QPushButton:disabled {
    background-color: $botao;
    color: $texto_desativado;
}

QPushButton[papel="primario"],
QPushButton[papel="primario-icone"] {
    background-color: $destaque;
    color: $texto_sobre_destaque;
    font-weight: 600;
}

QPushButton[papel="primario-icone"] {
    padding: 0;
}

QPushButton[papel="primario"]:hover,
QPushButton[papel="primario-icone"]:hover {
    background-color: $destaque_hover;
}

QPushButton[papel="primario"]:pressed,
QPushButton[papel="primario-icone"]:pressed {
    background-color: $destaque_pressionado;
}

QPushButton[papel="primario"]:disabled,
QPushButton[papel="primario-icone"]:disabled {
    background-color: $destaque_desativado;
    color: $texto_sobre_destaque;
}

QPushButton[papel="icone"] {
    background-color: transparent;
    padding: 0;
}

QPushButton[papel="icone"]:hover {
    background-color: $botao_hover;
}

QPushButton[papel="icone"]:pressed {
    background-color: $botao_pressionado;
}

QPushButton[papel="fechar"] {
    background-color: transparent;
    padding: 0;
    border-radius: 6px;
}

QPushButton[papel="fechar"]:hover,
QPushButton[papel="fechar"]:pressed {
    background-color: $perigo_fundo;
}

QMessageBox QPushButton {
    min-width: 72px;
}

/* ---------- Barra de status e dicas ---------- */

QStatusBar {
    background-color: $painel;
    color: $texto_suave;
    border-top: 1px solid $borda;
}

QStatusBar::item {
    border: none;
}

QToolTip {
    background-color: $painel;
    color: $texto;
    border: 1px solid $borda;
    padding: 4px 6px;
}

/* ---------- Barras de rolagem ---------- */

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: $rolagem;
    border-radius: 4px;
    min-height: 28px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: $rolagem_hover;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: $rolagem;
    border-radius: 4px;
    min-width: 28px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: $rolagem_hover;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
""")


def gerar_qss(p: Paleta) -> str:
    return _MODELO_QSS.substitute(asdict(p))