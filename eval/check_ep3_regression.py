"""Regresión sin red ni escrituras a datos funcionales, con evidencia JSON/JUnit.

Uso: python -m eval.check_ep3_regression --salida .cache/ep3/corrida
La carpeta debe ser nueva. No modifica .env ni registra sus valores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from time import perf_counter
import xml.etree.ElementTree as ET

from eval.aislamiento_ep3 import Aislamiento, configurar_offline


RAIZ = Path(__file__).resolve().parents[1]


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def artefactos() -> dict[str, str]:
    rutas = [RAIZ / '.env', *RAIZ.glob('data/*.db*'),
             *RAIZ.glob('storage/**/*'), *RAIZ.glob('.cache/embeddings*')]
    return {p.relative_to(RAIZ).as_posix(): huella(p) for p in rutas if p.is_file()}


def codigo_actual() -> dict[str, str]:
    return {p.relative_to(RAIZ).as_posix(): huella(p)
            for carpeta in ('src', 'tests', 'eval') for p in (RAIZ / carpeta).rglob('*.py')}


def ejecutar(salida: Path, pruebas: list[str]) -> int:
    salida = salida.resolve()
    salida.mkdir(parents=True, exist_ok=False)
    os.chdir(RAIZ)
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    configurar_offline()
    antes = artefactos()
    estado = {
        'schema_version': 1, 'tipo': 'simulada',
        'inicio_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=RAIZ, text=True).strip(),
        'git_status': subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all'], cwd=RAIZ, text=True),
        'dependencias': dict(sorted((d.metadata['Name'], d.version) for d in metadata.distributions() if d.metadata.get('Name'))),
        'archivos_codigo': codigo_actual(),
        'artefactos_antes': antes,
        'comando': ['python', '-m', 'eval.check_ep3_regression', '--salida', str(salida), *pruebas],
    }
    inicio = perf_counter()
    junit = salida / 'pytest.xml'
    argumentos = [*pruebas, '-q', '-p', 'no:cacheprovider', f'--junitxml={junit}']
    with Aislamiento(RAIZ) as aislamiento:
        import pytest
        with (salida / 'pytest.log').open('w', encoding='utf-8') as log:
            from contextlib import redirect_stdout, redirect_stderr
            with redirect_stdout(log), redirect_stderr(log):
                codigo = int(pytest.main(argumentos))
    estado.update(duracion_segundos=round(perf_counter() - inicio, 3), pytest_exit_code=codigo,
                  controles=aislamiento.controles, artefactos_despues=artefactos())
    estado['artefactos_sin_cambios'] = estado['artefactos_despues'] == antes
    estado['codigo_sin_cambios_durante_pruebas'] = codigo_actual() == estado['archivos_codigo']
    suites = ET.parse(junit).getroot().iter('testsuite')
    totales = {k: 0 for k in ('tests', 'failures', 'errors', 'skipped')}
    for suite in suites:
        for k in totales:
            totales[k] += int(suite.get(k, 0))
    totales['passed'] = totales['tests'] - sum(totales[k] for k in ('failures', 'errors', 'skipped'))
    estado['pruebas'] = totales
    estado['aprobado'] = (codigo == 0 and estado['artefactos_sin_cambios']
                          and estado['codigo_sin_cambios_durante_pruebas']
                          and aislamiento.aprobado())
    (salida / 'resultado.json').write_text(json.dumps(estado, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: estado[k] for k in ('aprobado', 'pruebas', 'controles', 'artefactos_sin_cambios', 'duracion_segundos')}, ensure_ascii=False))
    return 0 if estado['aprobado'] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', type=Path, required=True)
    parser.add_argument('pruebas', nargs='*', default=['tests'])
    args = parser.parse_args()
    return ejecutar(args.salida, args.pruebas)


if __name__ == '__main__':
    raise SystemExit(main())
