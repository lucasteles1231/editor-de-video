"""
As edições pedidas pela interface: uma por vez, numa thread, com progresso.

Uma thread e não processos: o modo "spawn" de multiprocessamento do Windows
reimportaria o servidor inteiro em cada processo filho, e uma edição já ocupa todos os
núcleos (o Whisper e o x264 usam vários sozinhos).
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from editor import render
from editor import saida as saida_mod
from editor.opcoes import OpcoesDeEdicao

#: Quanto cada etapa pesa na barra de progresso (início, fim).
PESOS = {"transcrevendo": (0.0, 0.35), "cortando": (0.35, 0.38),
         "desenhando": (0.38, 0.97), "finalizando": (0.97, 1.0), "pronto": (1.0, 1.0)}
NOMES = {"transcrevendo": "Transcrevendo a fala", "cortando": "Cortando os silêncios",
         "desenhando": "Desenhando legenda, zoom e ícones", "finalizando": "Finalizando o arquivo",
         "pronto": "Pronto"}


class Ocupado(Exception):
    """Já há uma edição rodando."""


@dataclass
class Tarefa:
    video: Path
    destino: Path
    edicao: OpcoesDeEdicao
    saida: saida_mod.OpcoesDeSaida
    previa_s: float | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    estado: str = "rodando"            # rodando | pronto | erro | cancelado
    etapa: str = "transcrevendo"
    fracao: float = 0.0
    detalhe: str = ""
    comeco: float = field(default_factory=time.monotonic)
    fim: float | None = None
    resultado: dict | None = None
    erro: str = ""
    cancelar: threading.Event = field(default_factory=threading.Event)
    versao: int = 0

    def total(self) -> float:
        a, b = PESOS.get(self.etapa, (0.0, 1.0))
        return a + (b - a) * min(1.0, max(0.0, self.fracao))

    def falta_s(self) -> float | None:
        """Quanto falta, pela velocidade do desenho (a etapa mais longa e mais regular)."""
        if self.estado != "rodando" or self.etapa != "desenhando" or self.fracao < 0.05:
            return None
        decorrido = time.monotonic() - self.comeco
        feito = self.total()
        return max(0.0, decorrido / max(feito, 1e-3) * (1 - feito))

    def para_dict(self) -> dict:
        return {"id": self.id, "estado": self.estado, "etapa": self.etapa,
                "etapa_nome": NOMES.get(self.etapa, self.etapa),
                "fracao": round(self.total(), 4), "detalhe": self.detalhe,
                "falta_s": self.falta_s(), "resultado": self.resultado, "erro": self.erro,
                "decorrido_s": round((self.fim or time.monotonic()) - self.comeco, 1),
                "versao": self.versao}


class Gerente:
    def __init__(self) -> None:
        self._trava = threading.Lock()
        self.tarefas: dict[str, Tarefa] = {}

    def ocupado(self) -> bool:
        return any(t.estado == "rodando" for t in self.tarefas.values())

    def iniciar(self, tarefa: Tarefa) -> Tarefa:
        with self._trava:
            if self.ocupado():
                raise Ocupado
            self.tarefas[tarefa.id] = tarefa
        threading.Thread(target=self._rodar, args=(tarefa,), daemon=True,
                         name=f"edicao-{tarefa.id}").start()
        return tarefa

    def _rodar(self, t: Tarefa) -> None:
        def progresso(etapa: str, fracao: float, detalhe: str) -> None:
            t.etapa, t.fracao = etapa, fracao
            if detalhe:
                t.detalhe = detalhe
            t.versao += 1

        try:
            r = render.editar(t.video, t.destino, t.edicao, t.saida, previa_s=t.previa_s,
                              progresso=progresso, cancelar=t.cancelar.is_set)
            t.resultado = r.para_dict()
            t.estado, t.etapa, t.fracao = "pronto", "pronto", 1.0
        except render.Cancelado:
            t.estado, t.detalhe = "cancelado", "edição cancelada"
            t.destino.unlink(missing_ok=True)
        except Exception as erro:
            t.estado, t.erro = "erro", f"{type(erro).__name__}: {erro}"
            t.detalhe = traceback.format_exc(limit=3)
            t.destino.unlink(missing_ok=True)
        finally:
            t.fim = time.monotonic()
            t.versao += 1


__all__ = ["NOMES", "PESOS", "Gerente", "Ocupado", "Tarefa"]
