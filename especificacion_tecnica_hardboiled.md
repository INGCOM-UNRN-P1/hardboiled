# Especificación Técnica y de Requisitos de Software: `hardboiled`

**Versión:** 1.0.0-draft  
**Estado:** Aprobado para implementación  
**Arquitectura Target:** RISC-V 32-bit (RV32I Bare-metal)  
**Gestor de Proyecto:** `uv` (Python 3.12+)

---

## 1. Visión General y Objetivos del Proyecto

`hardboiled` es una herramienta pedagógica por línea de comandos e interfaz TUI (Terminal User Interface) concebida para la enseñanza de programación en bajo nivel (lenguaje C), arquitectura de computadoras y sistemas embebidos.

El sistema proporciona un entorno de ejecución aislado y determinista donde los estudiantes pueden depurar programas C paso a paso (con breakpoints, step-into y step-over), inspeccionar registros y memoria en tiempo real, e interactuar con periféricos de hardware simulados mediante operaciones de entrada/salida mapeadas en memoria (MMIO) y tratamiento de interrupciones asíncronas.

### Objetivos Principales
* **Aislamiento Seguro:** Ejecución en espacio de usuario sin acceso a recursos directos del host mediante emulación de CPU con Unicorn Engine.
* **Depuración a Nivel de Código Fuente:** Inspección de binarios ELF mediante metadatos DWARF, sincronizando el puntero de instrucción con las líneas reales del archivo `.c`.
* **Hardware Modular Extensible:** Simulación de buses MMIO e inyección de interrupciones sin acoplarse al código de la interfaz gráfica.
* **Desacoplamiento Estricto:** Separación total entre el motor de emulación (backend/worker thread) y la capa de presentación (TUI Textual), permitiendo reemplazos futuros por frontends gráficos (PyQt, WebSockets) sin alterar el core.

---

## 2. Stack Tecnológico y Repositorio

* **Gestor de Dependencias y Entorno Virtual:** `uv`
* **Estándar de Control de Versiones:** Git con Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`)
* **Calidad y Formato de Código:** `ruff` (linter/formatter) y `mypy` (verificación de tipos estricta)
* **Motor de Simulación:** `unicorn` (`UC_ARCH_RISCV`, `UC_MODE_RISCV32`)
* **Análisis de Metadatos Binarios:** `pyelftools` (DWARF v4/v5)
* **Interfaz de Consola (TUI):** `textual`
* **Validación de Esquemas:** `pydantic` v2 (declaración de placas en TOML)

---

## 3. Mapa de Memoria y Modelo de Ejecución

La arquitectura emulada corresponde a un procesador **RISC-V 32-bit (RV32I)** con direccionamiento plano de 4 GB. El layout de memoria física se estructura en segmentos estrictos:

| Rango de Direcciones | Tamaño | Permisos | Descripción |
|---|---|---|---|
| `0x0000_0000 - 0x0000_FFFF` | 64 KB | `PROT_NONE` | Zona de trampa. Cualquier lectura, escritura o ejecución dispara un trap de puntero nulo. |
| `0x0001_0000 - 0x0001_FFFF` | 64 KB | `PROT_READ \| PROT_EXEC` | **Flash / ROM:** Contiene la tabla de vectores, `crt0.s`, sección `.text` y constantes `.rodata`. |
| `0x2000_0000 - 0x2000_FFFF` | 64 KB | `PROT_READ \| PROT_WRITE` | **SRAM:** Contiene variables globales (`.data`, `.bss`), heap y la pila (stack) que crece hacia abajo desde `0x2001_0000`. |
| `0x4000_0000 - 0x4000_0FFF` | 4 KB | Interceptado por Hook | **Espacio MMIO:** Sin backing store directo; mapeado al bus virtual de periféricos en Python. |

---

## 4. Requisitos Funcionales (RF)

### 4.1. Core del Emulador y Control de Recursos
* **RF-01 (Carga de Binario ELF):** El sistema debe parsear un archivo ELF generado para `riscv32-unknown-elf`, extrayendo y mapeando los segmentos cargables (`PT_LOAD`) en la memoria de Unicorn.
* **RF-02 (Límites de Ejecución):**
  * Cuota máxima de instrucciones configurable (`max_instructions`, por defecto $10^6$) para mitigar bucles infinitos no deseados.
  * Límite estricto de SRAM para detectar stack overflow si el registro `sp` ($x2$) desciende por debajo de `0x2000_0000`.
* **RF-03 (Trampas de Memoria):** Abortar la ejecución y emitir un evento descriptivo cuando el código intente acceder a segmentos no inicializados, violar permisos de segmento o desreferenciar punteros nulos.

### 4.2. Depurador Simbólico (DWARF Engine)
* **RF-04 (Mapeo Simbólico):** Resolución bidireccional entre la dirección del Program Counter ($PC$) y el par `(nombre_archivo.c, numero_linea)` a partir de la tabla `.debug_line`.
* **RF-05 (Comandos de Control de Flujo):**
  * `Step Into`: Ejecuta instrucciones hasta que el $PC$ apunte a una línea de código C distinta a la actual. Si se invoca una función, se detiene en su primera instrucción.
  * `Step Over`: Si la instrucción en el $PC$ es una llamada (`jal` / `jalr` afectando al link register $ra / x1$), el depurador inyecta un breakpoint efímero en la dirección siguiente ($PC + 4$) y ejecuta hasta alcanzarlo. En cualquier otro caso, actúa como un `Step Into`.
  * `Continue`: Reanuda la ejecución continua hasta encontrar un breakpoint o un trap.
  * `Toggle Breakpoint`: Permite fijar o remover puntos de parada por número de línea de código C o por dirección de memoria.
* **RF-06 (Inspección de Estado):** Acceso y volcado del valor de los 32 registros enteros (`x0` a `x31`) y visualización del contenido de la pila en torno a `sp`.

### 4.3. Bus de Hardware I/O Modular (MMIO)
* **RF-07 (Hooks de Memoria):** Interceptar lecturas (`UC_HOOK_MEM_READ`) y escrituras (`UC_HOOK_MEM_WRITE`) dentro del rango `0x4000_0000 - 0x4000_0FFF`.
* **RF-08 (Periféricos Base Suministrados):**
  * **Barra de LEDs (`0x4000_0000`):** Registro de escritura de 8/32 bits. Cada mutación emite una notificación a la vista.
  * **DIP Switches (`0x4000_0004`):** Registro de solo lectura donde el retorno refleja el estado de los interruptores configurados en la UI.
  * **Consola UART (`0x4000_0010`):** Registro de transmisión que captura bytes enviados por el firmware y los reenvía al búfer de texto de la consola simulada.
  * **Timer con IRQ (`0x4000_0020`):** Registro configurable con divisor de ciclos que genera una solicitud de interrupción periódica.

### 4.4. Controlador de Interrupciones Asíncronas (Virtual PIC)
* **RF-09 (Gestión de IRQs):** El controlador virtual en Python administra máscaras de interrupción (`irq_enable`) y líneas de solicitud (`irq_pending`).
* **RF-10 (Inyección de Contexto):** En el hook de ciclo (`UC_HOOK_CODE`), si las interrupciones están habilitadas y hay una IRQ activa:
  1. El emulador salva el $PC$ actual y los registros clave en la pila del firmware.
  2. Ajusta el $PC$ a la dirección de la rutina ISR asociada en la tabla de vectores.
  3. Al detectar la instrucción de retorno de interrupción (`mret`), restaura el contexto previo y reanuda el hilo normal.

### 4.5. Runtime y SDK de Abstracción (`hardboiled.h`)
* **RF-11 (Archivos de Arranque Provistos):**
  * `crt0.s`: Código de inicio en ensamblador que inicializa el puntero de pila (`sp = 0x20010000`), inicializa los segmentos `.data`/`.bss` y llama a `main()`.
  * `hardboiled.ld`: Linker script con las secciones alineadas a los segmentos emulados.
  * `hardboiled.h`: Cabecera C que encapsula los registros MMIO y el registro de handlers de interrupción mediante funciones pedagógicas (`led_set()`, `switch_get()`, `attach_irq()`).

---

## 5. Requisitos No Funcionales (RNF)

* **RNF-01 (Facilidad de Despliegue):** El proyecto debe instalarse de manera autocontenida mediante `uv venv && uv pip install -e .` en sistemas Linux, macOS y Windows (WSL2), sin exigir dependencias del sistema con privilegios administrativos (`sudo`).
* **RNF-02 (Concurrencia Thread-Safe):** La CPU emulada corre en un hilo de trabajo dedicado (`RunnerThread`). La UI corre en el hilo principal. La comunicación se realiza exclusivamente mediante colas de mensajes (`queue.Queue`) con tipos inmutables (`dataclasses`).
* **RNF-03 (Desacoplamiento Arquitectónico):** Ningún componente del simulador o hardware puede importar módulos de `textual` ni referencias a la capa de presentación.

---

## 6. Arquitectura de Comunicación (Patrón Event/Command)

```
+-------------------------------------------------------------------+
|                        Vista (Textual TUI)                        |
|  - Renderiza código fuente con línea activa e indicadores [B]     |
|  - Renderiza LEDs interactivos, Switches y consola UART           |
|  - Renderiza tabla de registros enteros y frame del stack         |
|  - Captura atajos de teclado (F5, F9, F10, F11) y clics           |
+---------------------------------+---------------------------------+
                                  |
               Colas de Paso de Mensajes (Thread-Safe)
               - cmd_queue: Envío de acciones desde UI a CPU
               - evt_queue: Notificaciones desde CPU a UI
                                  |
+---------------------------------v---------------------------------+
|                    Worker Thread (Unicorn Engine)                 |
|  - Bucle de simulación RV32I (UC_HOOK_CODE)                      |
|  - Gestor DWARF (Mapeo PC <-> Línea C)                            |
|  - Despachador MMIO (Lectura/Escritura de periféricos)            |
|  - Controlador de Interrupciones Virtuales                        |
|  - Monitor de recursos (instrucciones y stack guard)              |
+-------------------------------------------------------------------+
```

### Definición del Protocolo de Eventos

```python
# Comandos (UI -> Motor)
@dataclass(frozen=True)
class CmdStepInto: pass

@dataclass(frozen=True)
class CmdStepOver: pass

@dataclass(frozen=True)
class CmdContinue: pass

@dataclass(frozen=True)
class CmdToggleBreakpoint:
    line_number: int

@dataclass(frozen=True)
class CmdToggleSwitch:
    pin_index: int

# Eventos (Motor -> UI)
@dataclass(frozen=True)
class EvtCpuSuspended:
    pc: int
    source_file: str | None
    source_line: int | None
    registers: dict[str, int]
    cycle_count: int

@dataclass(frozen=True)
class EvtHardwareUpdated:
    device_name: str
    register_offset: int
    value: int

@dataclass(frozen=True)
class EvtUartOutput:
    char_code: int

@dataclass(frozen=True)
class EvtTrap:
    reason: str
    fault_address: int | None
```

---

## 7. Esquema de Configuración Declarativa (`board.toml`)

```toml
[board]
name = "lab-rv32-basics"
arch = "riscv32"
max_instructions = 5_000_000

[memory]
flash_base = "0x00010000"
flash_size_kb = 64
sram_base  = "0x20000000"
sram_size_kb  = 64
mmio_base  = "0x40000000"

[[peripherals]]
name = "leds"
type = "gpio_out"
offset = "0x00"
width_bits = 8

[[peripherals]]
name = "switches"
type = "gpio_in"
offset = "0x04"
width_bits = 4

[[peripherals]]
name = "uart0"
type = "uart"
offset = "0x10"

[[peripherals]]
name = "timer0"
type = "timer"
offset = "0x20"
irq_line = 0
```

---

## 8. Estructura del Repositorio

```text
hardboiled/
├── pyproject.toml
├── README.md
├── board.toml                  # Placa virtual por defecto
├── runtime/                    # Toolchain bare-metal provisto
│   ├── crt0.s                  # Startup, vector table y setup de SP
│   ├── hardboiled.ld           # Linker script
│   └── include/
│       └── hardboiled.h        # Headers pedagógicos para el alumno
├── src/
│   └── hardboiled/
│       ├── __init__.py
│       ├── cli.py              # Subcomandos: run, info, validate
│       ├── core/
│       │   ├── cpu.py          # Wrapper de Unicorn RV32I
│       │   ├── events.py       # Dataclasses de comandos y eventos
│       │   ├── runner.py       # Worker Thread y ciclo de ejecución
│       │   ├── debugger.py     # Lógica Step-Over, Step-Into y Breakpoints
│       │   ├── dwarf.py        # Parseo DWARF con pyelftools
│       │   └── pic.py          # Controlador de interrupciones virtuales
│       ├── hardware/
│       │   ├── bus.py          # Despachador central MMIO
│       │   ├── gpio.py         # Módulos de LEDs y Switches
│       │   ├── uart.py         # Módulo UART virtual
│       │   └── timer.py        # Temporizador e inyector de IRQs
│       └── ui/
│           ├── tui.py          # Aplicación principal Textual
│           └── widgets/
│               ├── code_view.py
│               ├── hardware_view.py
│               ├── registers_view.py
│               └── memory_view.py
└── tests/
    ├── test_cpu.py
    ├── test_mmio.py
    └── fixtures/               # Binarios ELF mínimos de prueba
```