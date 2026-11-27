"""Controles locales para evaluaciones simuladas; no modifica el entorno .env."""

import os
from pathlib import Path
import sys
import socket
from urllib.parse import unquote, urlsplit


def configurar_offline() -> None:
    os.environ.update({
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
        'LANGCHAIN_TRACING_V2': 'false', 'LANGSMITH_TRACING': 'false',
        'LANGCHAIN_API_KEY': '', 'LANGSMITH_API_KEY': '', 'EP3_OBSERVABILIDAD': '0',
        'STREAMLIT_BROWSER_GATHER_USAGE_STATS': 'false',
    })


class Aislamiento:
    def __init__(self, raiz: Path):
        self.raiz = raiz.resolve()
        self.activo = False
        self.controles = dict.fromkeys(('red_bloqueada', 'subprocesos_bloqueados',
                                       'escrituras_funcionales_bloqueadas', 'ipc_socketpair_local'), 0)

    def aprobado(self):
        return not any(v for k,v in self.controles.items() if k!='ipc_socketpair_local')

    @staticmethod
    def _socketpair_local(args):
        # Windows implementa socketpair con TCP loopback. Solo se permite el
        # socket/puerto creado por esa llamada concreta de la biblioteca estándar.
        if len(args)<2 or not isinstance(args[1],tuple): return False
        frame=sys._getframe(1)
        while frame:
            if frame.f_code.co_name=='_fallback_socketpair' and frame.f_code.co_filename==socket.__file__:
                d=frame.f_locals;destino=(d.get('addr'),d.get('port'))
                return (args[0] is d.get('csock') and args[1]==destino
                        and destino[0] in ('127.0.0.1','::1') and d['lsock'].getsockname()[:2]==destino)
            frame=frame.f_back
        return False

    def protegida(self, valor) -> bool:
        if not isinstance(valor, (str, bytes, os.PathLike)):
            return False
        texto = os.fsdecode(valor)
        if texto.startswith('file:'):
            texto = unquote(urlsplit(texto).path)
            if os.name == 'nt' and texto.startswith('/'):
                texto = texto[1:]
        ruta = Path(texto).resolve()
        return (ruta == self.raiz / '.env' or ruta.is_relative_to(self.raiz / 'storage')
                or ruta.is_relative_to(self.raiz / 'data') and '.db' in ruta.name
                or ruta.parent == self.raiz / '.cache' and ruta.name.startswith('embeddings'))

    def auditar(self, evento, args):
        if not self.activo:
            return
        if evento in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto', 'socket.sendmsg'):
            if evento=='socket.connect' and self._socketpair_local(args):
                self.controles['ipc_socketpair_local']+=1
                return
            self.controles['red_bloqueada'] += 1
            raise OSError('Red deshabilitada durante la evaluación EP3.')
        if evento == 'subprocess.Popen':
            self.controles['subprocesos_bloqueados'] += 1
            raise OSError('Subprocesos deshabilitados durante la evaluación EP3.')
        sqlite_escritura = (evento == 'sqlite3.connect' and
                            not (isinstance(args[0], str) and args[0].startswith('file:')
                                 and 'mode=ro' in urlsplit(args[0]).query.split('&')))
        escritura = (sqlite_escritura or
                     evento == 'open' and (isinstance(args[1], str) and any(c in args[1] for c in 'wax+')
                                          or isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                     or evento in ('os.remove', 'os.rename', 'os.rmdir'))
        if escritura and any(self.protegida(a) for a in args[:2]):
            self.controles['escrituras_funcionales_bloqueadas'] += 1
            raise OSError('Artefactos funcionales protegidos durante la evaluación EP3.')

    def __enter__(self):
        self.activo = True
        sys.addaudithook(self.auditar)
        return self

    def __exit__(self, *_):
        self.activo = False
