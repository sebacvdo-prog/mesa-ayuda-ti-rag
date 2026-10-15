"""Interfaz EP2: python -m src.ep2.cli. Reanuda la memoria de usuario y sesión."""

from __future__ import annotations

import argparse
from typing import Callable

from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ContextoEjecucion, DecisionConfirmacion, RespuestaAgenteEP2
from src.ep2.herramientas import HerramientasEP2


def mostrar_trazabilidad(tipo: str, valor) -> None:
    if tipo == "observacion":
        print(f"Observación [{valor.origen} · {valor.fecha.isoformat()}] {valor.resumen}")
        print("Procedencia:", "; ".join(valor.procedencia) or valor.origen)
        return
    print(f"\n{tipo.replace('_', ' ').capitalize()} · {valor.id} · revisión {valor.revision}")
    print("Objetivo:", valor.objetivo)
    for p in valor.pasos:
        print(f"  {p.id} · prioridad de paso {p.prioridad} · {p.herramienta} · {p.estado} · depende de {','.join(p.dependencias) or 'ninguno'} · {p.codigo}")
    print(f"Prioridad registrada: {valor.prioridad_registrada or 'sin consultar'}; propuesta: {valor.prioridad_propuesta or 'sin propuesta'}.")
    if valor.cambios:
        cambio = valor.cambios[-1]
        print(f"Cambio: {cambio.codigo} · {cambio.motivo}")
    if valor.impacto_reportado != "no_informado":
        print("Impacto:", valor.impacto_reportado, "· reporte no verificado ·", valor.criterio_prioridad)


def resolver_confirmaciones(
    agente: AgenteEP2, respuesta: RespuestaAgenteEP2, leer: Callable[[str], str] = input,
) -> None:
    """Solo un evento humano de esta interfaz puede confirmar una nota."""
    for solicitud in respuesta.confirmaciones:
        print(solicitud.mensaje)
        print(solicitud.texto)
        try:
            valor = leer("Escribe CONFIRMAR para registrar, POSPONER para revisar luego; otra respuesta cancela: ")
        except (EOFError, KeyboardInterrupt):
            valor = ""
        if valor.strip().upper() == "POSPONER":
            print("Propuesta pendiente, sin escritura. Al reabrir necesitarás una nueva vista previa y confirmación.")
            continue
        resultado = agente.confirmar_nota(DecisionConfirmacion(
            solicitud_id=solicitud.solicitud_id, huella=solicitud.huella,
            decision="confirmar" if valor.strip().upper() == "CONFIRMAR" else "cancelar",
        ))
        print(resultado.mensaje)
        if resultado.estado == "ok":
            print("Identificador de nota:", resultado.datos["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usuario", default="agente_demo")
    parser.add_argument("--sesion", default="sesion_demo")
    parser.add_argument("--perfil", choices=("agente", "usuario_final"), default="agente")
    argumentos = parser.parse_args()
    contexto = ContextoEjecucion(usuario_id=argumentos.usuario, sesion_id=argumentos.sesion,
                                  perfil=argumentos.perfil)
    agente = AgenteEP2(HerramientasEP2(contexto, AlmacenEP2()))
    # Asignación separada mantiene compatibilidad con fábricas inyectadas en tests.
    agente.configurar_trazador(mostrar_trazabilidad)
    print(f"EP2 · Modelo {agente.opciones.modelo} · Perfil {contexto.perfil}")
    print("Sesión de simulación local, sin autenticación empresarial. /salir termina.")
    print(f"Memoria persistente · Usuario {contexto.usuario_id} · Sesión {contexto.sesion_id}")
    print("Reutiliza estos identificadores y el perfil para continuar tras cerrar la CLI.")
    while True:
        try:
            consulta = input("Consulta: ")
        except (EOFError, KeyboardInterrupt):
            break
        if consulta.strip().lower() == "/salir":
            break
        respuesta = agente.responder(consulta)
        print(respuesta.texto)
        if respuesta.aviso_memoria:
            print(respuesta.aviso_memoria)
        print("Herramientas:", ", ".join(f"{t.nombre}:{t.codigo}" for t in respuesta.herramientas))
        resolver_confirmaciones(agente, respuesta)


if __name__ == "__main__":
    main()
