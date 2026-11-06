"""Lógica pura (sem Qt) da reordenação de notas por arrastar e soltar.

Um "slot" é uma posição de inserção entre as notas: o slot 0 fica antes da
primeira nota, o slot N depois da N-ésima (e última).
"""


def calcular_slot(centros_x, x) -> int:
    """Slot de inserção para um cursor na coordenada `x`.

    `centros_x` são os centros horizontais das notas, em ordem visual.
    O slot é o número de notas cujo centro está à esquerda do cursor.
    """
    return sum(1 for centro in centros_x if centro < x)


def indice_destino(origem: int, slot: int) -> int:
    """Índice final da nota movida, dado o índice de origem e o slot.

    Soltar logo antes (slot == origem) ou logo depois (slot == origem + 1)
    da própria nota não muda nada.
    """
    if slot in (origem, origem + 1):
        return origem

    return slot if slot < origem else slot - 1


def reordenar(itens, origem: int, slot: int) -> list:
    """Nova lista com o item de `origem` movido para o `slot` informado."""
    resultado = list(itens)
    destino = indice_destino(origem, slot)

    if destino != origem:
        resultado.insert(destino, resultado.pop(origem))

    return resultado
