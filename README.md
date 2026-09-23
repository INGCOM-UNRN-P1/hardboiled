# hardboiled

Emulador pedagógico de un microcontrolador **RISC-V 32 bits (RV32I) bare-metal**
con depurador de código C en la terminal. Pensado para enseñar programación de
bajo nivel, arquitectura de computadoras y sistemas embebidos: se ejecuta un
programa C paso a paso, se inspeccionan registros y pila, y se interactúa con
periféricos simulados (LEDs, switches, UART, timer con interrupciones).

- CPU emulada con [Unicorn Engine](https://www.unicorn-engine.org/): el programa
  nunca toca recursos del host.
- Depuración a nivel de fuente con la información DWARF del ELF (`-g`).
- Periféricos mapeados en memoria (MMIO) e interrupciones asíncronas.
- Motor y vista desacoplados: la TUI ([Textual](https://textual.textualize.io/))
  sólo intercambia mensajes inmutables con el motor por dos colas.

## Instalación

Requiere Python 3.12+ y [`uv`](https://docs.astral.sh/uv/). No hace falta `sudo`.

```bash
uv tool install "hardboiled[zig]"   # herramienta + compilador C para RV32I (zig)
uv tool install hardboiled          # sólo la herramienta (si ya tenés riscv*-gcc)
```

El extra `[zig]` instala el paquete `ziglang` dentro del entorno aislado de la
herramienta: no toca el sistema ni requiere `sudo`, pero pesa decenas de MB.

Desde el repositorio:

```bash
uv venv && uv pip install -e ".[zig]"   # instalación editable
uv sync                                 # entorno de desarrollo (tests, ruff, mypy, zig)
```

## Compilar un programa

```bash
hardboiled build programa.c                  # -> programa.elf
hardboiled build main.c util.c -o main.elf -O1 --march rv32im -v
```

`build` agrega solo el runtime incluido en el paquete y los flags de la placa:

| Archivo | Contenido |
|---|---|
| `crt0.s` | Arranque: inicializa `sp = 0x2001_0000`, copia `.data`, limpia `.bss`, llama a `main()` y define la tabla de vectores. |
| `hardboiled.ld` | Linker script alineado con el mapa de memoria de la placa. |
| `include/hardboiled.h` | SDK: `led_set()`, `switch_get()`, `uart_puts()`, `timer_start()`, `attach_irq()`, … |

El compilador se elige así: `--cc` (`auto`, `gcc`, `zig` o una ruta), si no la
variable `HARDBOILED_CC`, y si no el primero disponible entre una toolchain GNU
para RISC-V en el `PATH` (`riscv64-unknown-elf-gcc`, `riscv32-unknown-elf-gcc`,
`riscv-none-elf-gcc`, …) y el clang del extra `[zig]`. Otras opciones: `-O`,
`--march` (`rv32i`, `rv32im`, `rv32ic`, `rv32imc`), `-D`, `-I`, `--cflags` y
`-v` para ver el comando completo.

Para compilar a mano o desde un Makefile propio, `hardboiled runtime` imprime
las rutas del runtime instalado:

```bash
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -g -O0 -ffreestanding \
    -nostdlib -nostartfiles -I"$(hardboiled runtime --include)" \
    -T"$(hardboiled runtime --linker-script)" "$(hardboiled runtime --crt0)" \
    programa.c -lgcc -o programa.elf
```

`tests/fixtures/build.py` recompila con este mismo módulo los ELF de prueba.

## Uso

```bash
hardboiled run programa.c                   # compila (con caché) y abre la TUI
hardboiled run programa.elf                 # TUI, detenida al inicio de main()
hardboiled run programa.elf --headless      # sin TUI: UART a stdout, trampas a stderr
hardboiled run traps.elf --headless --switches 0b0011 --max-instructions 100000
hardboiled info programa.elf                # segmentos, uso de memoria, funciones, fuentes
hardboiled validate [board.toml]            # valida una placa
hardboiled board init                       # copia la placa por defecto a ./board.toml
```

Si existe `./board.toml` se usa como placa; si no, la placa por defecto que
viene con el paquete. `hardboiled board init` copia esa placa al directorio
actual para editarla y `hardboiled board show` la imprime. Con `--headless` se
ignora `clock_hz` (la ejecución no se demora) salvo que se pase `--realtime`.
Con `--headless`, el código de salida es el valor devuelto por `main()` (módulo
256), `3` si hubo una trampa y `2` ante errores de uso.

`run` acepta un ELF o fuentes `.c`/`.s` (con las mismas opciones de
compilación que `build`). Los fuentes se compilan en la caché del usuario
(`~/.cache/hardboiled/builds` en Linux, o `HARDBOILED_CACHE_DIR`) y sólo se
recompilan si cambian ellos, los encabezados de sus directorios, las opciones
o el compilador. Los mensajes del compilador van a stderr, así que en
`--headless` stdout contiene sólo la salida de la UART.

### Ejemplos incluidos

```bash
hardboiled examples                  # lista los ejemplos con su descripción
hardboiled demo                      # compila y abre la demo interactiva
hardboiled demo interrupciones       # cualquier ejemplo, con las opciones de run
hardboiled examples copy hola leds   # copia fuentes al directorio actual
hardboiled examples show errores     # imprime un ejemplo
```

`hola`, `leds`, `switches`, `interrupciones`, `errores` (catálogo de trampas
elegidas con los switches) y `demo`. `hardboiled demo` es además una buena
prueba de humo después de instalar.

### Teclas de la TUI

| Tecla | Acción |
|---|---|
| `F5` / `c` | Continue: corre hasta un breakpoint, una trampa o el fin |
| `F6` / `p` | Pausa una ejecución en curso |
| `F9` / `b` | Pone/quita un breakpoint en la línea del cursor (también: click en el margen) |
| `F10` / `n` | Step Over: siguiente línea sin entrar en las funciones |
| `F11` / `s` | Step Into: siguiente línea, entrando en las funciones llamadas |
| `0`–`7` | Conmuta un switch (también: click en el botón) |
| `r` | Reset de la placa |
| `q` | Salir |

`↑`/`↓`/`PgUp`/`PgDn` mueven el cursor en el código.

## La placa

### Mapa de memoria

| Rango | Tamaño | Permisos | Uso |
|---|---|---|---|
| `0x0000_0000 - 0x0000_FFFF` | 64 KB | ninguno | Trampa de punteros nulos |
| `0x0001_0000 - 0x0001_FFFF` | 64 KB | R X | Flash: vectores, `crt0`, `.text`, `.rodata`, imagen de `.data` |
| `0x2000_0000 - 0x2000_FFFF` | 64 KB | R W | SRAM: `.data`, `.bss`, heap, pila (desde `0x2001_0000` hacia abajo) |
| `0x4000_0000 - 0x4000_0FFF` | 4 KB | MMIO | Periféricos (sin memoria detrás: cada acceso va al bus en Python) |

### Periféricos (placa por defecto)

| Offset | Registro | Descripción |
|---|---|---|
| `0x000` | `LEDS` | 8 LEDs. Admite accesos de 8/16/32 bits; cada cambio se ve en la TUI. |
| `0x004` | `SWITCHES` | 4 DIP switches, sólo lectura. Escribirlos es una trampa. |
| `0x010` | `UART_TX` | Byte a transmitir a la consola. |
| `0x014` | `UART_STATUS` | Bit 0: listo para transmitir. |
| `0x020` | `TIMER_CTRL` | Bit 0 habilita, bit 1 genera IRQ. |
| `0x024` | `TIMER_RELOAD` | Período en ciclos (divisor). |
| `0x028` | `TIMER_COUNT` | Ciclos restantes (sólo lectura). |
| `0x02C` | `TIMER_STATUS` | Bit 0: venció (escribir 1 para limpiar). |
| `0xF00` | `PIC_ENABLE` | Máscara de IRQs habilitadas. |
| `0xF04` | `PIC_PENDING` | IRQs pendientes (escribir 1 para limpiar). |
| `0xF08` | `PIC_GLOBAL` | Bit 0: interrupciones habilitadas globalmente. |

### Interrupciones

`attach_irq(línea, handler)` registra una función C y habilita la línea;
`interrupts_enable()` activa el habilitador global. Cuando una IRQ habilitada
está pendiente, antes de la próxima instrucción la CPU virtual:

1. guarda el PC y los registros que el ABI no preserva (`ra`, `t0-t6`, `a0-a7`)
   en un marco de 80 bytes en la pila del programa;
2. salta a `__vector_table[línea]` (definida en `crt0.s`), que llama al handler;
3. al llegar al `mret` final restaura el marco y retoma el programa.

No hay anidamiento: mientras se atiende una IRQ las demás quedan pendientes.
`wait_for_interrupt()` (`wfi`) adelanta el reloj hasta la próxima interrupción.

### Trampas

La ejecución se aborta con un mensaje descriptivo ante: desreferencia de
puntero nulo, escritura en Flash, acceso a memoria no mapeada, salto a la SRAM,
registro MMIO inexistente o de sólo lectura, stack overflow (`sp` por debajo
de `0x2000_0000`), `wfi` sin ninguna interrupción que pueda despertar la CPU,
instrucción ilegal y cuota de instrucciones agotada (`max_instructions`).

### `board.toml`

Declara la placa: límites de ejecución, regiones de memoria y periféricos. Se
valida con pydantic (regiones alineadas y sin superposición, periféricos dentro
del espacio MMIO, líneas de IRQ únicas). Ver `board.toml` en la raíz. El campo
opcional `board.clock_hz` acompasa la emulación al reloj real para que un LED
que parpadea con el timer tenga una velocidad visible; sin él, la CPU corre tan
rápido como puede. El SDK (`hardboiled.h`) asume los offsets de la placa por
defecto.

## Arquitectura

```
Vista (ui/)            ── cmd_queue: CmdStepInto, CmdContinue, CmdToggleSwitch, … ──▶
  Textual, hilo principal                                                  RunnerThread (core/runner.py)
                       ◀── evt_queue: EvtCpuSuspended, EvtHardwareUpdated, EvtTrap, … ──
```

| Módulo | Responsabilidad |
|---|---|
| `core/events.py` | Protocolo: dataclasses inmutables de comandos y eventos. |
| `core/cpu.py` | Wrapper de Unicorn: memoria, hook de ciclo, trampas, stack guard, entrada/salida de ISR, `wfi`. |
| `core/debugger.py` | Breakpoints por línea o dirección, Step Into, Step Over, Continue. |
| `core/dwarf.py` / `core/elf.py` | Tabla de líneas DWARF (PC ⇄ archivo:línea), segmentos y símbolos. |
| `core/pic.py` | Controlador de interrupciones virtual. |
| `core/machine.py` | Arma la placa a partir de `board.toml`. |
| `core/runner.py` | Hilo de trabajo: atiende comandos y publica eventos. |
| `hardware/` | Bus MMIO y periféricos (GPIO, UART, timer). |
| `ui/` | Aplicación Textual y widgets. |

`core/` y `hardware/` no importan nada de la interfaz (un test lo verifica),
así que otro frontend sólo tiene que hablar el protocolo de `core/events.py`.

Algunas decisiones de implementación:

- El hook `UC_HOOK_CODE` corre **antes** de cada instrucción; para intervenir
  (breakpoint, IRQ, `mret`, fin de programa) detiene la emulación sin
  ejecutarla y el cambio de contexto se hace fuera de Unicorn.
- El código vive en Flash (sólo lectura), así que se escanea una única vez al
  cargar para indexar `mret`, `wfi`, `ebreak`/`ecall`, las llamadas
  (`jal`/`jalr` con `rd = ra`, usadas por Step Over) y las instrucciones que
  escriben `sp` (el stack guard sólo lee `sp` después de ellas).
- Step Over pone un breakpoint efímero en `PC + 4` que sólo vale si `sp`
  volvió a su valor: una llamada recursiva no lo dispara antes de tiempo.
- Los pasos no se detienen dentro de una ISR que empezó durante el paso (los
  breakpoints sí), para que una IRQ asíncrona no "secuestre" el step.
- Los pasos saltean el código sin fuente disponible (compiler-rt, libgcc).
- El espacio MMIO se mapea con `mmio_map` de Unicorn: cada lectura y escritura
  de ese rango se atiende en Python, sin memoria de respaldo.

## Desarrollo

```bash
uv run pytest                          # tests (incluye la TUI con el pilot de Textual)
uv run ruff check . && uv run ruff format --check .
uv run mypy                            # modo estricto
uv run python tests/fixtures/build.py  # recompilar los ELF de prueba
```

Commits con [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
