from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

# Todos os desenhos usam uma grade lógica de 24 x 24.
_RESOLUCAO = 2  # pixels reais por pixel lógico (nitidez em telas HiDPI)


def _sol(p, cor):
    p.drawEllipse(QPointF(12, 12), 4, 4)

    for i in range(8):
        p.save()
        p.translate(12, 12)
        p.rotate(i * 45)
        p.drawLine(QPointF(0, -7.5), QPointF(0, -10.5))
        p.restore()


def _lua(p, cor):
    externo = QPainterPath()
    externo.addEllipse(QPointF(12, 12), 8, 8)

    interno = QPainterPath()
    interno.addEllipse(QPointF(16, 9), 7, 7)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cor)
    p.drawPath(externo.subtracted(interno))


def _mais(p, cor):
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _fechar(p, cor):
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def _copiar(p, cor):
    p.drawRoundedRect(QRectF(9, 9, 11, 12), 2, 2)

    folha = QPainterPath()
    folha.moveTo(6, 15)
    folha.lineTo(6, 6)
    folha.lineTo(15, 6)
    p.drawPath(folha)


def _transcrever(p, cor):
    """Moldura de scanner com uma linha de texto ao centro."""
    for x, y, dx, dy in (
        (4, 4, 1, 1),
        (20, 4, -1, 1),
        (4, 20, 1, -1),
        (20, 20, -1, -1),
    ):
        canto = QPainterPath()
        canto.moveTo(x + dx * 5, y)
        canto.lineTo(x, y)
        canto.lineTo(x, y + dy * 5)
        p.drawPath(canto)

    p.drawLine(QPointF(8, 12), QPointF(16, 12))


def _logo(p, cor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cor)
    p.drawRoundedRect(QRectF(2, 2, 20, 20), 6, 6)

    caneta = QPen(Qt.GlobalColor.white, 2)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(caneta)

    p.drawLine(QPointF(7, 9), QPointF(17, 9))
    p.drawLine(QPointF(7, 13), QPointF(17, 13))
    p.drawLine(QPointF(7, 17), QPointF(13, 17))


_DESENHOS = {
    "sol": _sol,
    "lua": _lua,
    "mais": _mais,
    "fechar": _fechar,
    "copiar": _copiar,
    "transcrever": _transcrever,
    "logo": _logo,
}


def _renderizar(desenho, cor, tamanho):
    pixmap = QPixmap(tamanho * _RESOLUCAO, tamanho * _RESOLUCAO)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(_RESOLUCAO)

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(tamanho / 24, tamanho / 24)

    cor = QColor(cor)

    caneta = QPen(cor, 2)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    p.setPen(caneta)
    p.setBrush(Qt.BrushStyle.NoBrush)

    desenho(p, cor)
    p.end()

    return pixmap


def _montar_icone(desenho, cor, cor_desativada, tamanho):
    icone = QIcon()

    icone.addPixmap(
        _renderizar(desenho, cor, tamanho),
        QIcon.Mode.Normal,
    )
    # Pixmap próprio para "desativado": evita o cinza automático do Qt.
    icone.addPixmap(
        _renderizar(desenho, cor_desativada or cor, tamanho),
        QIcon.Mode.Disabled,
    )

    return icone


def criar_icone(nome, cor, tamanho=24, cor_desativada=None) -> QIcon:
    return _montar_icone(
        _DESENHOS[nome], cor, cor_desativada, tamanho
    )


def criar_icone_carregando(cor, angulo, tamanho=24) -> QIcon:
    """Arco girando; `angulo` em graus (use um QTimer para animar)."""

    def desenho(p, cor_):
        p.translate(12, 12)
        p.rotate(angulo)
        p.translate(-12, -12)
        p.drawArc(QRectF(4, 4, 16, 16), 0, 270 * 16)

    return _montar_icone(desenho, cor, None, tamanho)