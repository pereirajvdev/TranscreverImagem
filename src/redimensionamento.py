"""Lógica pura (sem Qt) do redimensionamento de notas pela divisória.

Duas notas vizinhas dividem um espaço fixo: o que uma ganha, a outra
perde. As larguras são medidas em pixels; o QHBoxLayout as controla por
fatores de esticamento (stretch), então o resultado é convertido de
volta para esses fatores, mantendo a soma do par.
"""


def largura_esquerda(esquerda: int, direita: int, deslocamento: int,
                     minimo: int) -> int:
    """Nova largura da nota da esquerda após arrastar a divisória.

    `esquerda` e `direita` são as larguras no início do arraste e
    `deslocamento` é o quanto o cursor andou (positivo = para a
    direita). Nenhuma das duas fica abaixo de `minimo`; uma nota que
    já começou mais estreita que isso apenas não encolhe mais.
    """
    total = esquerda + direita
    menor = min(minimo, esquerda)
    maior = total - min(minimo, direita)

    return max(menor, min(esquerda + deslocamento, maior))


def repartir_estico(estico_total: int, esquerda: int, total: int):
    """Divide `estico_total` entre as duas notas, proporcional à largura.

    Devolve (estico_esquerda, estico_direita), ambos >= 1 e somando
    `estico_total`. `esquerda` é a largura desejada da primeira nota e
    `total` a largura das duas juntas.
    """
    if total <= 0 or estico_total < 2:
        metade = estico_total // 2
        return metade, estico_total - metade

    parte = round(estico_total * esquerda / total)
    parte = max(1, min(parte, estico_total - 1))

    return parte, estico_total - parte
