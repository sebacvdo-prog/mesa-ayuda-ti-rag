"""Notas y auditoría transaccionales, exclusivamente en una base EP2 marcada."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from src import config
from src.ep2.contratos import ContextoEjecucion

DIRECTORIO_EP2 = config.DIR_ALMACENAMIENTO / "ep2"
APPLICATION_ID = 0x45503231  # EP21; evita adoptar o migrar bases ajenas
VERSION_ESQUEMA = 1


class ConflictoIdempotencia(ValueError):
    """La misma operación se intentó reutilizar con un contenido diferente."""


class AlmacenEP2:
    """El archivo se llama siempre agent.db dentro del directorio EP2 indicado.

    El directorio alternativo permite pruebas aisladas. Se rechazan enlaces al
    ITSM original y bases existentes sin la marca EP2, sin modificar su esquema.
    """

    def __init__(self, directorio: Path = DIRECTORIO_EP2) -> None:
        self._directorio = Path(directorio).resolve()
        self._ruta = self._directorio / "agent.db"
        self._verificar_ruta()
        self._directorio.mkdir(parents=True, exist_ok=True)
        nueva = not self._ruta.exists() or self._ruta.stat().st_size == 0
        with self._conexion(comprobar_marca=False) as conexion:
            if not nueva:
                self._verificar_marca(conexion)
                return
            conexion.execute("BEGIN IMMEDIATE")
            # Otro proceso puede haber inicializado el archivo mientras se
            # esperaba el bloqueo. Revisar dentro de la misma transacción.
            marca = conexion.execute("PRAGMA application_id").fetchone()[0]
            if marca == APPLICATION_ID:
                self._verificar_marca(conexion)
                return
            if marca != 0 or conexion.execute("SELECT name FROM sqlite_master").fetchone():
                raise ValueError("La base existente no pertenece al esquema EP2 esperado.")
            conexion.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            conexion.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
            conexion.execute("""
                CREATE TABLE notas (
                    id TEXT PRIMARY KEY,
                    usuario_id TEXT NOT NULL,
                    sesion_id TEXT NOT NULL,
                    id_operacion TEXT NOT NULL,
                    solicitud_id TEXT NOT NULL UNIQUE,
                    ticket_id TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    huella TEXT NOT NULL,
                    origen TEXT NOT NULL CHECK (origen = 'confirmacion_explicita_usuario'),
                    confirmado_en TEXT NOT NULL,
                    creado_en TEXT NOT NULL,
                    UNIQUE (usuario_id, sesion_id, id_operacion)
                )
            """)
            conexion.execute("""
                CREATE TABLE auditoria (
                    id INTEGER PRIMARY KEY,
                    nota_id TEXT NOT NULL UNIQUE REFERENCES notas(id),
                    usuario_id TEXT NOT NULL,
                    sesion_id TEXT NOT NULL,
                    evento TEXT NOT NULL CHECK (evento = 'nota_registrada'),
                    huella TEXT NOT NULL,
                    fecha TEXT NOT NULL
                )
            """)

    @property
    def ruta(self) -> Path:
        return self._ruta

    def _verificar_ruta(self) -> None:
        resuelta = self._ruta.resolve()
        original = config.RUTA_BD.resolve()
        if resuelta.parent != self._directorio or resuelta == original:
            raise ValueError("La base EP2 debe estar separada del ITSM original.")
        if self._ruta.exists() and original.exists() and self._ruta.samefile(original):
            raise ValueError("La base EP2 no puede ser un enlace al ITSM original.")

    @staticmethod
    def _verificar_marca(conexion: sqlite3.Connection) -> None:
        marca = conexion.execute("PRAGMA application_id").fetchone()[0]
        version = conexion.execute("PRAGMA user_version").fetchone()[0]
        if marca != APPLICATION_ID or version != VERSION_ESQUEMA:
            raise ValueError("La base existente no pertenece al esquema EP2 esperado.")

    @contextmanager
    def _conexion(self, comprobar_marca: bool = True) -> Iterator[sqlite3.Connection]:
        self._verificar_ruta()
        # En operación normal, mode=rw impide crear por accidente una base vacía
        # si alguien movió o borró el archivo después de inicializarlo.
        uri = self._ruta.as_uri() + ("?mode=rw" if comprobar_marca else "?mode=rwc")
        conexion = sqlite3.connect(uri, uri=True, timeout=5)
        conexion.row_factory = sqlite3.Row
        try:
            conexion.execute("PRAGMA foreign_keys = ON")
            if comprobar_marca:
                self._verificar_marca(conexion)
            with conexion:
                yield conexion
        finally:
            conexion.close()

    def buscar_operacion(
        self, contexto: ContextoEjecucion, id_operacion: str,
    ) -> dict | None:
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM notas WHERE usuario_id = ? AND sesion_id = ? AND id_operacion = ?",
                (contexto.usuario_id, contexto.sesion_id, id_operacion),
            ).fetchone()
        return dict(fila) if fila else None

    def listar_notas(self, contexto: ContextoEjecucion, ticket_id: str) -> list[dict]:
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT * FROM notas WHERE usuario_id = ? AND sesion_id = ? AND ticket_id = ? "
                "ORDER BY creado_en, id",
                (contexto.usuario_id, contexto.sesion_id, ticket_id),
            ).fetchall()
        return [dict(fila) for fila in filas]

    def _registrar_nota_confirmada(
        self, contexto: ContextoEjecucion, *, id_operacion: str, solicitud_id: str,
        ticket_id: str, texto: str, huella: str, fecha: str,
    ) -> tuple[dict, bool]:
        """Frontera interna: la llama el servicio tras la confirmación humana.

        BEGIN IMMEDIATE serializa las comprobaciones de idempotencia. Nota y
        auditoría se confirman juntas o ambas se revierten ante cualquier error.
        """
        with self._conexion() as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            existente = conexion.execute(
                "SELECT * FROM notas WHERE usuario_id = ? AND sesion_id = ? AND id_operacion = ?",
                (contexto.usuario_id, contexto.sesion_id, id_operacion),
            ).fetchone()
            if existente:
                if existente["huella"] != huella:
                    raise ConflictoIdempotencia("La operación ya tiene otro contenido.")
                return dict(existente), True
            nota_id = str(uuid4())
            conexion.execute(
                "INSERT INTO notas (id, usuario_id, sesion_id, id_operacion, solicitud_id, "
                "ticket_id, texto, huella, origen, confirmado_en, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nota_id, contexto.usuario_id, contexto.sesion_id, id_operacion,
                 solicitud_id, ticket_id, texto, huella, "confirmacion_explicita_usuario", fecha, fecha),
            )
            conexion.execute(
                "INSERT INTO auditoria (nota_id, usuario_id, sesion_id, evento, huella, fecha) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nota_id, contexto.usuario_id, contexto.sesion_id, "nota_registrada", huella, fecha),
            )
            fila = conexion.execute("SELECT * FROM notas WHERE id = ?", (nota_id,)).fetchone()
            return dict(fila), False
