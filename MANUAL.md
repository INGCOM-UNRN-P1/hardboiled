# Manual de Uso y Guía de Referencia: hardboiled

`hardboiled` es un emulador pedagógico bare-metal para microcontroladores virtuales basados en la arquitectura RISC-V 32 bits (RV32I/RV32IMC). Integra un entorno TUI en terminal con depuración a nivel C (DWARF), inspección de periféricos en tiempo real, ejecución reversible ("paso atrás") y detección asistida de errores comunes de programación en bajo nivel.

---

## 1. Arquitectura y Mapa de Memoria

El microcontrolador virtual emulado implementa la arquitectura RISC-V RV32I (con soporte configurable para extensiones M y C). Posee 32 registros generales (`x0`–`x31`), un contador de programa (`pc`) y un mapa de memoria físico dividido en cuatro regiones fundamentales:

| Región | Rango de Direcciones | Tamaño | Permisos | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| **Zona de Trampa NULL** | `0x0000_0000` – `0x0000_FFFF` | 64 KB | Ninguno | Cualquier lectura, escritura o salto genera una excepción inmediata de puntero nulo. |
| **Flash ROM** | `0x0001_0000` – `0x0001_FFFF` | 64 KB | Lectura / Ejecución (`R-X`) | Aloja vector de interrupción, código compilado (.text) y constantes (.rodata). Escrituras disparan `flash-write`. |
| **SRAM** | `0x2000_0000` – `0x2000_7FFF` | 32 KB | Lectura / Escritura (`RW-`) | Variables globales (`.data`, `.bss`), heap y la pila del sistema (`sp` inicializado en `0x2000_8000`). |
| **MMIO (Periféricos)** | `0x4000_0000` – `0x4000_03FF` | 1 KB | Lectura / Escritura (`RW-`) | Registros de control y estado de periféricos mapeados en memoria. |

Cualquier acceso por fuera de estos rangos físicos aborta la ejecución con la trampa `unmapped`.

### Mapa de Registros MMIO (`0x4000_0000`)

| Offset | Nombre | Registro | Modo | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `0x00` | `LEDS` | `0x4000_0000` | R/W | 8 LEDs de propósito general (bits 0–7). |
| `0x04` | `SWITCHES` | `0x4000_0004` | R | 8 interruptores de palanca (bits 0–7). |
| `0x08` | `BUTTONS` | `0x4000_0008` | R | 4 pulsadores de entrada (bits 0–3). |
| `0x0C` | `SEG7_0` | `0x4000_000C` | R/W | Display de 7 segmentos: dígito 0 (derecha) o modo raw. |
| `0x10` | `SEG7_1` | `0x4000_0010` | R/W | Display de 7 segmentos: dígito 1 (izquierda). |
| `0x14` | `SEG7_MODE`| `0x4000_0014` | R/W | Modo del display: `0` = raw (segmentos individuales), `1` = BCD/decimal, `2` = hexadecimal. |
| `0x20` | `UART_TX` | `0x4000_0020` | W | Transmisión serie: escribir un byte envía el caracter a la consola. |
| `0x24` | `UART_RX` | `0x4000_0024` | R | Recepción serie: leer entrega el byte recibido pendiente. |
| `0x28` | `UART_STAT`| `0x4000_0028` | R | Bit 0: `RX_READY` (hay datos), Bit 1: `TX_EMPTY` (buffer libre). |
| `0x2C` | `UART_CTRL`| `0x4000_002C` | R/W | Bit 0: `RX_IRQ_EN` (interrupción por recepción). |
| `0x30` | `TIMER_CNT`| `0x4000_0030` | R/W | Contador ascendente de ciclos de reloj. |
| `0x34` | `TIMER_CMP`| `0x4000_0034` | R/W | Comparador de disparo para interrupción periódica. |
| `0x38` | `TIMER_CTRL`| `0x4000_0038` | R/W | Bit 0: `ENABLE`, Bit 1: `AUTO_RELOAD`, Bit 2: `IRQ_EN`. |
| `0x40` | `PIC_PEND` | `0x4000_0040` | R/W | Interrupciones pendientes (escribir 1 limpia la bandera). |
| `0x44` | `PIC_EN` | `0x4000_0044` | R/W | Máscara de interrupciones habilitadas. |
| `0x48` | `PIC_PRIO` | `0x4000_0048` | R/W | Niveles de prioridad por línea de IRQ. |

---

## 2. Instalación y Diagnóstico

### Instalación vía `uv`

Instalación estándar:
```bash
uv tool install hardboiled
```

Instalación recomendada con compilador Clang embebido (no requiere instalar GCC externo):
```bash
uv tool install "hardboiled[zig]"
```

Instalación en entorno de desarrollo local:
```bash
git clone https://github.com/usuario/hardboiled.git
cd hardboiled
uv venv
uv pip install -e ".[dev,zig]"
```

### Verificación del Entorno (`hardboiled doctor`)

Ejecutá `doctor` para comprobar toolchains, emuladores y dependencias del sistema:
```bash
hardboiled doctor
```
El comando reporta:
1. Versión de Python y soporte de biblioteca estándar.
2. Estado de `unicorn-engine`.
3. Toolchain RISC-V detectado (`riscv64-unknown-elf-gcc`, `riscv32-unknown-elf-gcc` o Clang integrado).
4. Estado del debugger y soporte DWARF (`pyelftools`).

---

## 3. Flujo de Trabajo y Compilación

### Crear un Nuevo Proyecto

```bash
hardboiled new mi_proyecto
cd mi_proyecto
```

Estructura creada:
```
mi_proyecto/
├── main.c           # Punto de entrada y ejemplos del SDK
├── hardboiled.h     # Declaraciones del SDK bare-metal
├── board.toml       # Configuración del hardware virtual
├── compile_flags.txt# Banderas para clangd / LSP
└── Makefile         # Targets de compilación opcionales
```

### Compilar el Firmware (`hardboiled build`)

```bash
# Compilación estándar (busca main.c o el archivo especificado)
hardboiled build main.c

# Compilación con nivel de optimización y símbolos de depuración
hardboiled build main.c -O0 -g -o firmware.elf

# Compilación seleccionando extensiones de la arquitectura
hardboiled build main.c --march rv32imc
```

Banderas soportadas por `build`:
- `-O, --opt-level`: Nivel de optimización (`0`, `1`, `2`, `s`). Por defecto `0` para facilitar depuración.
- `-g, --debug`: Incluye símbolos DWARF requeridos para inspección de variables y código fuente C en la TUI.
- `--march`: Extensiones (`rv32i`, `rv32im`, `rv32ic`, `rv32imc`).
- `--toolchain`: Forzar `gcc` o `clang`.

---

## 4. Interfaz TUI y Depuración Interactiva

Iniciá el entorno gráfico interactivo:
```bash
hardboiled run firmware.elf
```

### Distribución de la Pantalla

```
┌─ Código C / Desensamblado ───────────────────────┐┌─ Placa Virtual ──────────────────┐
│ 12  int main(void) {                             ││ LEDs:   [●][○][●][○][○][○][○][○] │
│ 13      led_set(0x05);                           ││ SW:     [0][0][0][0][0][0][1][1] │
│ 14  =>  seg_show_hex(0x2A);                      ││ 7SEG:   [ 2 ][ A ]               │
│ 15      while(1);                                ││ UART:   "Iniciando sistema...\n" │
└──────────────────────────────────────────────────┘└──────────────────────────────────┘
┌─ Pestañas de Inspección ──────────────────────────────────────────────────────────────┐
│ [Variables (DWARF)]  [Registros (x)]  [Pila]  [Memoria (Hex)]  [Puntos]  [Llamadas]   │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### Atajos de Teclado y Control de Ejecución

| Tecla | Acción | Descripción |
| :--- | :--- | :--- |
| `F5` / `c` | **Continuar** | Ejecuta instrucciones hasta el próximo breakpoint o trampa. |
| `F6` / `s` | **Paso a paso (Step In)** | Avanza a la siguiente línea C o instrucción (entra en funciones). |
| `F7` / `n` | **Paso sobre (Step Over)**| Ejecuta la línea actual sin entrar en subfunciones. |
| `F8` / `u` | **Paso atrás (Step Back)**| Rebobina el estado exacto de CPU y memoria a la instrucción previa. |
| `F9` / `b` | **Alternar Breakpoint** | Fija o elimina un punto de interrupción en la línea seleccionada. |
| `F10` / `o` | **Paso afuera (Step Out)**| Ejecuta hasta retornar de la función actual. |
| `F4` | **Ejecutar hasta el cursor**| Corre hasta la línea donde está posicionado el cursor. |
| `B` | **Breakpoint Condicional**| Define una condición en C/registro (ej. `x10 == 0x2A`). |
| `d` | **Modo Mixto / ASM** | Alterna entre vista de código C puro y C intercalado con assembly. |
| `h` | **Mapa de Calor** | Activa visualización por frecuencia de ejecución de instrucciones. |
| `r` | **Reiniciar** | Restablece CPU, periféricos y recarga el firmware a su estado inicial. |
| `q` | **Salir** | Cierra la interfaz TUI. |

### Pestañas del Inspector

1. **Variables (DWARF):** Muestra variables locales y globales activas, con su tipo de dato original en C, dirección en memoria y valor decimal/hexadecimal.
2. **Registros (`x`):** Listado completo de `x0` a `x31` con su alias ABI estándar (`zero`, `ra`, `sp`, `gp`, `tp`, `t0-t6`, `s0-s11`, `a0-a7`), además del `pc` actual.
3. **Pila (Stack):** Inspección dinámica del stack frame actual, indicando offsets respecto a `sp`, valores almacenados y direcciones de retorno (`ra`).
4. **Memoria (Hex):** Visor hexdump navegable en cualquier rango físico. Permite saltar a direcciones fijas con `g` (ej. `0x20000000`).
5. **Puntos:** Registro de breakpoints activos y watchpoints configurados (disparo por lectura o escritura en memoria).
6. **Llamadas (Backtrace):** Árbol de llamadas a funciones activas reconstruido mediante análisis de frames.

---

## 5. Modo Headless y Automatización (CI/CD)

Para scripts de evaluación, integración continua o grading automatizado, ejecutá sin interfaz visual:

```bash
# Ejecutar hasta finalizar o alcanzar límite de ciclos
hardboiled run firmware.elf --headless --max-cycles 1000000

# Salida estructurada en JSON
hardboiled run firmware.elf --headless --json

# Volcado detallado de traza de instrucciones ejecutadas
hardboiled run firmware.elf --headless --trace traza.log
```

### Testing Automatizado (`hardboiled test`)

Permite validar suites de prueba declaradas en archivos TOML:

```bash
hardboiled test firmware.elf --suite casos.toml
```

Estructura de un archivo de casos de prueba (`casos.toml`):
```toml
[[test]]
name = "Verificar inicialización de periféricos"
max_cycles = 50000
inputs.switches = 0x03
inputs.buttons = 0x01
expect.leds = 0x03
expect.seg7 = 0x42
expect.trap = "none"

[[test]]
name = "Verificar detección de puntero nulo"
max_cycles = 10000
expect.trap = "null-pointer"
```

---

## 6. Programación con el SDK (`hardboiled.h`)

El archivo [`hardboiled.h`](/hardboiled/src/hardboiled/runtime/include/hardboiled.h) expone macros y funciones bare-metal directas para interactuar con la placa virtual:

```c
#include "hardboiled.h"

// --- GPIO: LEDs, Switches, Botones ---
void led_set(uint8_t mask);         // Escribe en LEDs (0x00 a 0xFF)
uint8_t switch_get(void);           // Lee estado de los 8 switches
uint8_t button_get(void);           // Lee estado de los 4 pulsadores

// --- Display 7 Segmentos ---
void seg_show_dec(uint8_t value);   // Modo decimal: muestra valor 00 a 99
void seg_show_hex(uint8_t value);   // Modo hexadecimal: muestra valor 00 a FF
void seg_show_raw(uint8_t d1, uint8_t d0); // Modo raw: segmentos directos

// --- Comunicación Serie (UART) ---
void uart_putc(char c);             // Envía un byte
void uart_puts(const char *str);    // Envía una cadena terminada en NULL
int  uart_getc(void);               // Retorna caracter o -1 si no hay datos
int  uart_has_data(void);           // 1 si RX_READY está activo

// --- Timer e Interrupciones ---
void timer_start(uint32_t compare, uint8_t auto_reload);
void timer_stop(void);
void irq_enable(uint8_t irq_line);
void irq_disable(uint8_t irq_line);
void irq_set_priority(uint8_t irq_line, uint8_t priority);
void wfi(void);                     // Espera por interrupción (Wait For Interrupt)
```

### Ejemplo de Programa Bare-Metal

```c
#include "hardboiled.h"

void isr_timer(void) {
    static uint8_t count = 0;
    count++;
    led_set(count);
    seg_show_hex(count);
}

int main(void) {
    uart_puts("Iniciando Hardboiled OS...\r\n");
    
    // Configura Timer para disparar cada 50.000 ciclos
    timer_start(50000, 1);
    irq_enable(IRQ_TIMER);
    
    while (1) {
        if (button_get() & 0x01) {
            uart_puts("Boton 0 pulsado\r\n");
        }
        wfi();
    }
    return 0;
}
```

---

## 7. Catálogo de Trampas y Diagnóstico de Errores

El emulador implementa monitoreo en hardware virtual para atrapar errores arquitecturales antes de que corrompan el estado de la máquina:

| Trampa | Disparador | Causa Frecuente |
| :--- | :--- | :--- |
| `null-pointer` | Acceso a `0x0000_0000`–`0x0000_FFFF` | Desreferenciar puntero nulo o no inicializado (`*ptr = 0`). |
| `flash-write` | Escritura en `0x0001_0000`–`0x0001_FFFF` | Intento de modificar variables marcadas `const` o puntero corrupto apuntando al código. |
| `unmapped` | Acceso a direcciones no asignadas | Desbordamiento de arrays, índices fuera de rango o punteros flotantes. |
| `bad-jump` | Salto a dirección no mapeada | Retorno de función corrupto (`ra` pisado en stack) o salto vía puntero a función inválido. |
| `stack-overflow` | `sp` desciende debajo del límite seguro de SRAM | Recursión infinita, arrays locales masivos en el stack. |
| `misaligned` | Acceso `lw`/`sw` con dirección no múltiplo de 4 | Casting indebido de punteros de distinto tamaño sin respetar alineación. |
| `illegal-instruction`| Decodificación de opcode inválido | Salto a datos binarios o uso de instrucciones no habilitadas en `--march`. |
| `deadlock` | Instrucción `wfi` sin interrupciones pendientes ni habilitadas | Bloqueo total de CPU en espera de eventos que nunca ocurrirán. |

Para obtener una explicación pedagógica interactiva desde la terminal:
```bash
hardboiled explain null-pointer
hardboiled explain stack-overflow
```

---

## 8. Tutoriales y Ejemplos Integrados

### Tutorial Interactivo

El CLI provee una secuencia didáctica paso a paso para aprender RISC-V y periféricos:

```bash
# Iniciar tutorial
hardboiled tutorial start

# Verificar solución del ejercicio actual
hardboiled tutorial check

# Avanzar al siguiente nivel
hardboiled tutorial next
```

### Galería de Ejemplos

Listar y desplegar programas de demostración provistos con la herramienta:
```bash
# Listar ejemplos disponibles
hardboiled examples list

# Desplegar un ejemplo en el directorio actual
hardboiled examples copy blinky
hardboiled examples copy uart_echo
hardboiled examples copy timer_irq

# Compilar y ejecutar demo de inmediato
hardboiled demo blinky
```

---

## 9. Configuración del Hardware (`board.toml`)

Cada proyecto puede personalizar las capacidades del hardware virtual modificando `board.toml`:

```toml
[cpu]
arch = "rv32i"          # rv32i, rv32im, rv32ic, rv32imc
clock_hz = 10000000     # Frecuencia virtual del microcontrolador

[memory]
flash_size_kb = 64
sram_size_kb = 32
trap_null = true        # Activa zona trampa de 64 KB en 0x00000000

[peripherals.uart]
enabled = true
baudrate = 115200

[peripherals.timer]
enabled = true
irq_line = 0

[peripherals.gpio]
leds = 8
switches = 8
buttons = 4
```
