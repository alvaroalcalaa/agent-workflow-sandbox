# Agent Workflow Sandbox 🤖🧪

Prueba qué ocurre con un flujo de agentes cuando falla una herramienta, se agotan los reintentos o hay pocas tareas que puedan ejecutarse a la vez. Simula dependencias y duraciones en **tiempo virtual**, con una traza cronológica y un informe HTML/JSON.

Creado el **31 de octubre de 2026**. Python **3.10+**, biblioteca estándar únicamente; sin instalación de paquetes, modelos, claves ni servicios. Código y escenarios originales bajo licencia MIT.

## Instalación y primer ejemplo

```bash
git clone https://github.com/alvaroalcalaa/agent-workflow-sandbox.git
cd agent-workflow-sandbox
python sandbox.py examples/retry-success.json --json report.json --html report.html
python -m unittest -v
```

Abre `report.html` en tu navegador. El JSON también se imprime en la terminal. La demo representa un flujo ficticio de preparación de un prototipo de videojuego: diseño → arte y comprobación → empaquetado. Los nombres son etiquetas: **no se ejecuta ninguna de esas operaciones**.

| Escenario | Resultado esperado | Duración virtual | Código de salida |
|---|---|---:|---:|
| `retry-success.json` | La comprobación falla una vez, se reintenta y permite empaquetar | 7 | 0 |
| `blocked-release.json` | La comprobación agota sus dos intentos y bloquea el empaquetado | 6 | 1 |

```bash
python sandbox.py examples/blocked-release.json --json blocked.json --html blocked.html
```

Ese segundo comando termina con **1 intencionadamente**. El informe se genera igualmente y muestra `lint: failed`, `package: blocked`; `art` sigue ejecutándose hasta terminar.

## Definir un escenario

```json
{
  "max_parallel": 2,
  "tasks": [
    {"id": "fetch", "duration": 2, "outcomes": ["error", "success"], "max_attempts": 2, "retry_delay": 3},
    {"id": "summarize", "duration": 4, "depends_on": ["fetch"]}
  ]
}
```

| Campo | Significado | Predeterminado / límite |
|---|---|---|
| `max_parallel` | Máximo de intentos simultáneos, incluidos reintentos | 2; de 1 a 16 |
| `id` | Identificador único, ASCII, letras/números/guion/guion bajo | Obligatorio; de 1 a 64 caracteres |
| `depends_on` | Tareas que deben terminar correctamente antes de empezar | Lista vacía |
| `duration` | Duración de **cada intento** | 1; entero de 1 a 3600 |
| `outcomes` | Resultado programado del intento 1, 2, etc. | `["success"]`; de 1 a 5 valores `success`/`error` |
| `max_attempts` | Máximo total de intentos, incluido el primero | 1; de 1 a 5 |
| `retry_delay` | Espera virtual después de un error recuperable | 0; entero de 0 a 3600 |

Todas las duraciones comparten la unidad que elijas (por ejemplo, segundos virtuales). No hay pausas de tiempo real. Si faltan resultados para un intento, se repite el último de `outcomes`. Por ejemplo, `["error"]` falla siempre; `["error", "success"]` se recupera si se permiten al menos dos intentos. Tras el primer éxito la tarea termina y no consume más resultados.

Se admiten entre 1 y 100 tareas en un archivo UTF-8 de hasta 1 MiB. Se rechazan ciclos, dependencias inexistentes/repetidas, claves JSON duplicadas, IDs inválidos y enteros fuera de rango. Los booleanos no cuentan como enteros. Los campos desconocidos se ignoran: no incluyas comandos esperando que se ejecuten.

## Política de ejecución

El planificador recorre una máquina de estados por tarea: `pending` → `running` → `success`; un error pasa de nuevo a `pending` si quedan intentos o a `failed` si se agotaron. Las dependientes de una tarea `failed` o `blocked` pasan a `blocked`, sin gastar intentos. Las ramas independientes continúan hasta terminar.

Las tareas listas compiten por capacidad en **orden lexicográfico de ID**, sin prioridades especiales para reintentos. Una espera de reintento libera el hueco. Si una tarea se vuelve elegible mientras todos los huecos están ocupados, espera al siguiente disponible. Se procesan todas las finalizaciones de un mismo instante antes de iniciar nuevas tareas; los empates de finalización también se ordenan por ID. No hay interrupción de intentos en curso.

Por ello, los mismos datos producen la misma traza aunque cambies el orden de las tareas en la entrada. Es una política determinista para experimentar, **no un optimizador de duración mínima**.

## Leer los informes

- `all_succeeded`: todas las tareas terminaron correctamente.
- `makespan`: último instante virtual procesado; incluye esperas y ramas que continúan tras un fallo.
- `tasks`: estado final, intentos, primer inicio y finalización o momento de bloqueo por tarea. `first_start: null` significa que nunca se ejecutó.
- `events`: eventos `start`, `success`, `error`, `retry_scheduled` y `blocked`, con tiempo e ID. `eligible_at` es el momento más temprano de reintento, no una garantía de inicio.

Los informes contienen los IDs y dependencias, pero no copian otros campos arbitrarios de entrada. El HTML no carga recursos externos. `--json` y `--html` son opcionales; las rutas no pueden coincidir entre sí ni sobrescribir la entrada. Los archivos de salida existentes se reemplazan. Un fallo de escritura puede dejar un informe parcial.

Códigos de salida: **0** todo correcto; **1** hay fallos definitivos o bloqueos; **2** argumentos, datos o escritura incorrectos. Esto permite comprobar escenarios desde un script o CI sin invocar herramientas reales.

## Límites reales y validación

Es un **simulador de orquestación**, no un agente con LLM ni un ejecutor de herramientas. Los resultados se programan manualmente: no predice la fiabilidad o duración real de un modelo. No hay llamadas de red, procesos de tareas, persistencia, cancelación, probabilidades, backoff exponencial, colas distribuidas ni compensaciones de operaciones parcialmente realizadas. Una tarea solo transmite éxito o fallo; no produce datos para la siguiente.

No se ha probado integración con LangGraph, MCP, un proveedor de modelos ni un orquestador externo. Las pruebas ejecutan la CLI local y verifican resultados conocidos: concurrencia, esperas, reintentos, fallos en cascada, ramas independientes, empates, determinismo y rechazo de grafos inválidos. Los ejemplos son ficticios y no contienen datos privados.

## Dependencias y licencia

Solo módulos estándar de Python (`heapq`, `json`, `argparse`, `html`, etc.). Consulta `LICENSE` (MIT).
