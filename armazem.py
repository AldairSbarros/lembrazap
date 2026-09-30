"""Persistência em JSON com escrita atômica e lock de processo.

Mesmo padrão validado no refactor do AletheIA: leitura tolerante a arquivo
ausente/corrompido, escrita via arquivo temporário + ``os.replace`` (atômica no
POSIX e no Windows) e ``atualizar()`` para o ciclo ler→mutar→gravar sob lock.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class JsonStore:
    """Arquivo JSON com leitura tolerante e escrita atômica thread-safe."""

    _lock_global = threading.RLock()

    def __init__(self, caminho: Path | str, padrao: Any = None) -> None:
        """Inicializa o store com o caminho do arquivo e o valor padrão (dict/list vazio)."""
        self.caminho = Path(caminho)
        self._padrao: Any = {} if padrao is None else padrao

    def ler(self) -> Any:
        """Lê o JSON do disco; retorna o padrão se o arquivo não existir ou estiver corrompido."""
        with self._lock_global:
            if not self.caminho.exists():
                return json.loads(json.dumps(self._padrao))
            try:
                with open(self.caminho, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return json.loads(json.dumps(self._padrao))

    def gravar(self, dados: Any) -> None:
        """Grava o JSON de forma atômica (tempfile + fsync + os.replace)."""
        with self._lock_global:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.caminho.parent), prefix=".tmp_", suffix=".json"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(dados, fh, ensure_ascii=False, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.caminho)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise

    def atualizar(self, fn_mutacao: Callable[[T], Any]) -> T:
        """Executa ler→mutar→gravar sob lock, retornando o dado já mutado."""
        with self._lock_global:
            dados = self.ler()
            fn_mutacao(dados)
            self.gravar(dados)
            return dados
