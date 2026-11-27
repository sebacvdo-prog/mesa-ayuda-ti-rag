"""Muestra reproducible de telemetría: LangChain/FAISS/SQLite locales y LLM simulado.

python -m eval.check_ep3_observabilidad --salida .cache/ep3/muestra
No usa Groq, no carga modelos de embeddings ni toca las bases originales.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from eval.aislamiento_ep3 import Aislamiento, configurar_offline
from eval.check_ep3_regression import RAIZ, artefactos


def ejecutar(salida: Path) -> dict:
    configurar_offline()
    salida = salida.resolve()
    salida.mkdir(parents=True, exist_ok=False)
    antes = artefactos()
    with Aislamiento(RAIZ) as aislamiento:
        from langchain_core.documents import Document
        from langchain_core.embeddings import Embeddings
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage
        from langchain_community.vectorstores import FAISS
        import httpx
        from openai import RateLimitError
        from data.seed_db import crear_base
        from src.ep2.agente import AgenteEP2
        from src.ep2.almacenamiento import AlmacenEP2
        from src.ep2.contratos import ContextoEjecucion
        from src.ep2.herramientas import HerramientasEP2
        from src.ep3.contratos_v2 import leer_evento
        from src.ep3.observabilidad import Observabilidad
        from src.retriever import ConectorITSM, RecuperadorVectorial

        class EmbeddingsSimulados(Embeddings):
            def embed_documents(self, texts):
                return [[1.0, 0.0] for _ in texts]
            def embed_query(self, text):
                return [1.0, 0.0]

        class ModeloSimulado(FakeMessagesListChatModel):
            rechazar: bool = True
            def bind_tools(self, herramientas, **kwargs):
                return self
            def invoke(self, input, config=None, **kwargs):
                if self.rechazar:
                    self.rechazar = False
                    response = httpx.Response(429, headers={'retry-after': '0'},
                                              request=httpx.Request('POST', 'https://sin-red.invalid'))
                    raise RateLimitError('Rechazo simulado.', response=response,
                                         body={'code': 'rate_limit_exceeded'})
                return super().invoke(input, config=config, **kwargs)

        def llamada(nombre, argumentos, numero):
            return AIMessage(content='', tool_calls=[{'name': nombre, 'args': argumentos, 'id': f'c{numero}'}])

        ticket = 'INC-2026-0411'
        selecciones = [('consultar_ticket', {'ticket_id': ticket}),
                       ('consultar_sla', {'prioridad': 'P2'}),
                       ('buscar_procedimiento', {'consulta': 'procedimiento VPN FortiClient'}),
                       ('consultar_ticket', {'ticket_id': ticket}),
                       ('consultar_sla', {'prioridad': 'P2'}),
                       ('analizar_incidente', {'ticket_id': ticket}),
                       ('buscar_procedimiento', {'consulta': 'procedimiento VPN FortiClient'})]
        llm = ModeloSimulado(responses=[llamada(n, a, i) for i, (n, a) in enumerate(selecciones)])
        doc = Document(page_content='Procedimiento simulado VPN: revisar conexión; escalar a Nivel 2 si persiste.',
                       metadata={'titulo': 'KB-RED-02 · VPN', 'documento': 'kb_conectividad_vpn.md',
                                 'fuente': 'interna', 'nivel_acceso': 'publico_interno',
                                 'fecha_vigencia': '2026-01-01'})
        faiss = FAISS.from_embeddings([(doc.page_content, [1.0, 0.0])], EmbeddingsSimulados(),
                                      metadatas=[doc.metadata])
        with TemporaryDirectory(prefix='ep3-simulacion-') as temporal:
            carpeta = Path(temporal)
            ruta = carpeta / 'itsm.db'
            crear_base(ruta)
            itsm_antes = ruta.read_bytes()
            almacen = AlmacenEP2(carpeta / 'funcional')
            servicio = HerramientasEP2(ContextoEjecucion(usuario_id='demo_ep3', sesion_id='demo_ep3', perfil='agente'),
                                       almacen, ConectorITSM(ruta))
            with Observabilidad(salida, tipo_ejecucion='simulada') as obs:
                agente = AgenteEP2(servicio, llm=llm, recuperador=RecuperadorVectorial(almacen=faiss),
                                   observabilidad=obs)
                inicial = agente.responder(f'Consulta ticket {ticket}, su SLA y recupera el procedimiento VPN FortiClient.')
                impacto = agente.responder('Ahora varios usuarios de la misma sucursal están afectados por la VPN. Reevalúa el reporte.')
                vaciada = obs.flush()
                salud = obs.estadisticas()
            with almacen._conexion() as c:
                sin_notas = c.execute('SELECT COUNT(*) FROM notas').fetchone()[0] == 0
                sin_auditoria = c.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0] == 0
            controles_funcionales = {
                'respuestas_ok': inicial.estado == impacto.estado == 'ok',
                'mismo_plan_adaptado': inicial.plan_final is not None and impacto.plan_final is not None
                    and inicial.plan_final.id == impacto.plan_final.id,
                'itsm_temporal_intacto': ruta.read_bytes() == itsm_antes,
                'sin_notas': sin_notas, 'sin_auditoria': sin_auditoria, 'cola_vaciada': vaciada,
            }
        with closing(sqlite3.connect((salida / 'observabilidad.db').as_uri() + '?mode=ro', uri=True)) as c:
            eventos = [leer_evento(f[0]) for f in c.execute('SELECT contenido_json FROM eventos ORDER BY rowid')]
    controles_funcionales['artefactos_originales_intactos'] = antes == artefactos()
    resumen = {
        'version_esquema': 1, 'tipo_ejecucion': 'simulada',
        'consultas': sum(e.evento == 'consulta_fin' for e in eventos),
        'herramientas': sum(e.evento == 'herramienta_fin' for e in eventos),
        'errores_modelo': sum(e.evento == 'modelo_error' for e in eventos),
        'reintentos_modelo': sum(e.evento == 'modelo_reintento' for e in eventos),
        'eventos_planificacion': sum(e.componente == 'planificacion' for e in eventos),
        'eventos_total': len(eventos),
        'latencias_consulta_ms': [e.duracion_ms for e in eventos if e.evento == 'consulta_fin'],
        'salud_telemetria': salud, 'controles': aislamiento.controles,
        'verificaciones': controles_funcionales,
    }
    resumen['aprobado'] = (all(controles_funcionales.values()) and aislamiento.aprobado()
                           and salud['descartados'] == salud['fallos_instrumentacion'] == 0)
    (salida / 'resultado.json').write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return resumen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', type=Path, required=True)
    args = parser.parse_args()
    resultado = ejecutar(args.salida)
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado['aprobado'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
