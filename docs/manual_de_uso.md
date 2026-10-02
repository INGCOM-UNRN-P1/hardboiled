# Manual de Uso y Guía de Referencia: hardboiled

`hardboiled` es un emulador pedagógico bare-metal de un microcontrolador RISC-V de 32 bits (RV32I, con
las extensiones M y C opcionales). Integra una TUI en la terminal con depuración a nivel de C (DWARF),
periféricos mapeados en memoria que se ven y se manejan en vivo, paso atrás y trampas que explican los
errores típicos de la programación de bajo nivel.

Este manual resume lo que se usa en clase. El [README](../README.md) es la referencia completa (GPIO
bidireccional, ADC, rebote de contactos, guion de entrada, avisos y arquitectura interna).

---

## 1. Arquitectura y Mapa de Memoria

La CPU virtual tiene 32 registros generales (`x0`–`x31`) y el contador de programa (`pc`). El conjunto
de instrucciones lo declara la placa con `isa` en `[board]` (`rv32i` por defecto). El mapa de memoria
de la placa por defecto es:

| Rango | Tamaño | Permisos | Uso |
| :--- | :--- | :--- | :--- |
| `0x0000_0000` – `0x0000_FFFF` | 64 KB | ninguno | Trampa de punteros nulos: leer, escribir o saltar ahí detiene el programa. |
| `0x0001_0000` – `0x0001_FFFF` | 64 KB | R X | Flash: vectores, `crt0`, `.text`, `.rodata` e imagen de `.data`. Escribirla es una trampa. |
| `0x2000_0000` – `0x2000_FFFF` | 64 KB | R W | SRAM: `.data`, `.bss`, heap y pila (desde `0x2001_0000` hacia abajo). |
| `0x4000_0000` – `0x4000_0FFF` | 4 KB | MMIO | Periféricos: cada acceso va al bus de periféricos. |

Un acceso fuera de estas regiones detiene el programa con la trampa `unmapped`.

### Mapa de Registros MMIO (base `0x4000_0000`)

Los offsets de la placa por defecto. El SDK (`hardboiled.h`) y el linker script se **generan a partir
de la placa**: con un `board.toml` propio cambian, y `hardboiled gen-header [board.toml]` imprime los
vigentes. En la TUI, `?` muestra el mapa de la placa cargada.

<!-- registros: la tabla se verifica contra la placa por defecto en tests/test_manual.py -->

| Offset | Registro | Descripción |
| :--- | :--- | :--- |
| `0x000` | `LEDS` | 8 LEDs, un bit por LED. Admite accesos de 8/16/32 bits. |
| `0x004` | `SWITCHES` | 4 DIP switches, sólo lectura. Escribirlos es una trampa. |
| `0x010` | `UART_TX` | Byte a transmitir a la consola. |
| `0x014` | `UART_STATUS` | Bit 0: listo para transmitir; bit 1: hay un byte recibido. |
| `0x018` | `UART_RX` | Siguiente byte recibido (0 si no hay). |
| `0x01C` | `UART_CTRL` | Bit 0: pedir la IRQ 1 mientras haya bytes recibidos. |
| `0x020` | `TIMER_CTRL` | Bit 0 habilita, bit 1 genera IRQ. |
| `0x024` | `TIMER_RELOAD` | Período en ciclos (divisor). |
| `0x028` | `TIMER_COUNT` | Ciclos restantes hasta el próximo vencimiento (sólo lectura). |
| `0x02C` | `TIMER_STATUS` | Bit 0: venció (escribir 1 para limpiar). |
| `0x030` | `BUTTONS_STATE` | 4 botones: bit en 1 mientras está presionado (sólo lectura). |
| `0x034` | `BUTTONS_IRQ_EN` | Botones que piden la IRQ 2. |
| `0x038` | `BUTTONS_EDGE` | Por botón: 0 avisa al presionar, 1 al soltar. |
| `0x03C` | `BUTTONS_PENDING` | Flancos detectados (escribir 1 limpia y retira la IRQ). |
| `0x040` | `SEG_DIGITS` | Display de 4 dígitos: un byte por dígito (el 0 a la derecha), segmentos a-g en los bits 0-6 y el punto en el 7. |
| `0xF00` | `PIC_ENABLE` | Máscara de IRQs habilitadas. |
| `0xF04` | `PIC_PENDING` | IRQs pendientes (escribir 1 para limpiar). |
| `0xF08` | `PIC_GLOBAL` | Bit 0: interrupciones habilitadas globalmente. |
| `0xF0C` | `PIC_ACTIVE` | Línea que se está atendiendo (`0xFFFFFFFF` si ninguna). |

Líneas de interrupción de la placa por defecto: `IRQ_TIMER0` = 0, `IRQ_UART0` = 1 e `IRQ_BUTTONS` = 2.
Leer o escribir un offset que no es un registro, o escribir uno de sólo lectura, es la trampa `mmio`.

---

## 2. Instalación y Diagnóstico

### Instalación vía `uv`

Instalación estándar (desde el repositorio; hardboiled no se publica en PyPI):
```bash
uv tool install git+https://github.com/INGCOM-UNRN-P1/hardboiled
```

Instalación recomendada, con el compilador C para RV32I incluido (el paquete `ziglang` queda dentro
del entorno aislado de la herramienta: no requiere `sudo` ni instalar GCC para RISC-V):
```bash
uv tool install "hardboiled[zig] @ git+https://github.com/INGCOM-UNRN-P1/hardboiled"
```

Desde un clon del repositorio:
```bash
git clone https://github.com/INGCOM-UNRN-P1/hardboiled.git
cd hardboiled
uv sync          # entorno de desarrollo: tests, ruff, mypy y zig
```

Para actualizar: `uv tool upgrade hardboiled`.

### Verificación del Entorno (`hardboiled doctor`)

```bash
hardboiled doctor
```

Verifica Python, el emulador, el runtime, la configuración, el compilador (compila y ejecuta un
programa de prueba) y la terminal. Es lo primero que conviene adjuntar en una consulta; con `--json`
el informe sale en JSON.

---

## 3. Flujo de Trabajo y Compilación

### Crear un Nuevo Proyecto

```bash
hardboiled new mi-tp
cd mi-tp
hardboiled run main.c
```

Estructura creada:
```
mi-tp/
├── main.c             # punto de entrada
├── board.toml         # la placa (copia de la placa por defecto)
├── Makefile           # make, make run, make headless y make clean
├── compile_flags.txt  # target RV32I y ruta de hardboiled.h para clangd
└── .gitignore
```

`hardboiled new mi-tp --example interrupciones` parte de un ejemplo incluido. Si se reinstala
hardboiled y cambia la ruta del runtime, `hardboiled new . --editor-only` regenera
`compile_flags.txt`.

### Compilar el Firmware (`hardboiled build`)

```bash
# Compilación estándar: programa.c -> programa.elf
hardboiled build programa.c

# Varios fuentes, salida, optimización, extensión M y el comando completo
hardboiled build main.c util.c -o main.elf -O1 --march rv32im -v
```

`build` agrega el runtime del paquete (`crt0.s`, el linker script y `hardboiled.h`) y compila siempre
con símbolos de depuración. Opciones:

- `-o`: archivo de salida.
- `-O`: nivel de optimización (`0` por defecto: con `-O1` o más el paso a paso salta líneas).
- `--march`: `rv32i`, `rv32im`, `rv32ic` o `rv32imc` (por defecto, el `isa` de la placa).
- `--cc`: compilador: `auto`, `gcc`, `zig` o una ruta (también la variable `HARDBOILED_CC`).
- `-D` e `-I`: macros y directorios de includes; `--cflags`: flags extra (`--cflags="-std=c99"`).
- `--board`: otra placa (por defecto `./board.toml` si existe).
- `-v`: muestra el comando del compilador.

`hardboiled run` acepta también fuentes `.c`/`.s` con las mismas opciones: los compila en la caché del
usuario y sólo recompila si cambiaron. Para compilar a mano, `hardboiled runtime` imprime las rutas del
runtime (`--include`, `--linker-script`, `--crt0`).

---

## 4. Interfaz TUI y Depuración Interactiva

```bash
hardboiled run main.c          # compila (con caché) y abre la TUI, detenida al inicio de main()
hardboiled run programa.elf
```

La pantalla muestra el código C (con el desensamblado intercalado si se pide), la placa (LEDs,
switches, botones, display y la consola de la UART) y las pestañas de inspección: **Variables**,
**Registros**, **Pila**, **Memoria**, **Puntos** y **Llamadas**.

### Atajos de Teclado y Control de Ejecución

| Tecla | Acción |
| :--- | :--- |
| `F5` / `c` | Continue: corre hasta un breakpoint, una trampa o el fin |
| `F6` / `p` | Pausa una ejecución en curso |
| `F9` / `b` | Pone o quita un breakpoint en la línea del cursor (también: click en el margen) |
| `F10` / `n` | Step Over: siguiente línea sin entrar en las funciones |
| `F11` / `s` | Step Into: siguiente línea, entrando en las funciones llamadas |
| `Shift+F11` / `o` | Step Out: termina la función actual e informa el valor devuelto |
| `F7` / `i` | Stepi: una sola instrucción de máquina |
| `F8` / `u` | Paso atrás: vuelve al estado previo al último comando de ejecución |
| `F4` / `g` | Run to cursor: ejecuta hasta la línea del cursor sin dejar breakpoint |
| `0`–`7` | Conmuta un switch (también: click en el switch) |
| `B` / `Ctrl+F9` | Breakpoint condicional en la línea del cursor (`i == 3`, `#5`, `n > 2 #2`) |
| `w` | Watchpoint: vigila una expresión y detiene cuando su valor cambia |
| `d` | Muestra u oculta el desensamblado mixto (C + RV32I) |
| `h` | Mapa de calor: instrucciones ejecutadas por línea desde el último Reset |
| `x` | Cambia el formato de los registros: hex, con signo, sin signo, ASCII, símbolo |
| `f` | Abre otro archivo fuente del programa |
| `?` | Ayuda: atajos vigentes, marcadores y mapa de memoria de la placa |
| `+` / `-` / `=` | Reloj de la CPU al doble / a la mitad / alterna fijo y sin límite |
| `r` | Reset de la placa |
| `q` | Salir |

Si la terminal captura alguna tecla (F10 abre el menú en GNOME Terminal, F11 pasa a pantalla
completa), los atajos se reasignan en `[keys]` del `config.toml` del usuario (`hardboiled config
init` lo crea), por ejemplo `step_over = "f2,n"`.

### Pestañas del Inspector

1. **Variables:** parámetros y locales de la función en curso (respetando el alcance de los bloques) y
   las globales, con su tipo C: enteros, `char`, `enum`, punteros (con lo apuntado expandible),
   arreglos, estructuras, uniones y campos de bits. Lo que cambió desde la última detención se resalta.
2. **Registros:** el estado crudo de `x0`–`x31` con sus nombres del ABI y el `pc`.
3. **Pila:** la pila separada por marcos: qué función ocupa cada palabra, dónde guardó `ra` y `s0`,
   dónde vive cada variable local y, si hubo una interrupción, el contexto que guardó la CPU.
4. **Memoria:** volcado hexadecimal y ASCII de Flash o SRAM a partir de una dirección, un símbolo o una
   expresión (`counter`, `&results`, `0x20000000`, `p`). El espacio MMIO no se lee, porque leerlo
   tendría efectos sobre los periféricos.
5. **Puntos:** breakpoints y watchpoints (Supr los quita). Se recuerdan entre sesiones en
   `.hardboiled/`, junto al programa.
6. **Llamadas:** la pila de llamadas (`main → sum_squares → square`), incluidas las entradas de
   interrupción; elegir un marco muestra su línea y sus variables.

Mientras la TUI está abierta, si el programa se recompila se vuelve a cargar solo (`--no-watch` lo
desactiva).

---

## 5. Modo Headless y Automatización (CI/CD)

Sin interfaz, la salida de la UART va a stdout y las trampas a stderr:

```bash
# Ejecutar hasta terminar, con switches iniciales y una cuota de instrucciones
hardboiled run programa.elf --headless --switches 0b0011 --max-instructions 100000

# Resultado en JSON (la salida de la UART va dentro del objeto)
hardboiled run programa.elf --headless --json

# Traza por instrucción (.csv o .jsonl) y perfil de funciones y líneas más ejecutadas
hardboiled run programa.elf --headless --trace traza.csv
hardboiled run programa.elf --headless --profile
```

Otras opciones de `run`: `--uart-input ARCHIVO` (bytes que llegan por la UART; `-` es la entrada
estándar), `--script ARCHIVO` (guion de estímulos en ciclos dados), `--trace-limit N` y `--realtime`
(respetar el `clock_hz` de la placa).

Códigos de salida con `--headless`: el valor que devolvió `main()` (módulo 256), `3` si hubo una
trampa o se agotó la cuota de instrucciones y `2` ante errores de uso.

### Testing Automatizado (`hardboiled test`)

Ejecuta el programa sin interfaz con entradas fijas y compara lo esperado. Termina con `0` si todo
coincide y con `1` si algo falla, y muestra las diferencias de la UART línea por línea:

```bash
hardboiled test main.c --switches 5 --expect-uart esperado.txt --expect-exit 3
hardboiled test main.c --expect-trap null-pointer     # o --expect-trap '*'
hardboiled test main.c --suite casos.toml              # varios casos
```

Una suite describe cada caso con sus entradas (`switches`, `uart_input` o `uart_input_file`, `script`
o un guion en línea `at = [...]`, `max_instructions`) y lo esperado (`expect_uart` o
`expect_uart_file`, `expect_uart_contains`, `expect_exit` o `expect_trap`). Las rutas son relativas al
archivo de la suite:

```toml
[[case]]
name = "eco en mayúsculas"
script = "entrada.toml"
expect_uart_file = "esperado.txt"
expect_exit = 3

[[case]]
name = "sale enseguida"
uart_input = "q"
expect_uart = "listo\nfin\n"

[[case]]
name = "detecta el puntero nulo"
expect_trap = "null-pointer"
```

El programa se compila y carga una sola vez, y cada caso arranca de un Reset. `expect_exit` compara el
valor completo que devolvió `main()`. Si un caso no espera una trampa, que ocurra una, o que se agote
la cuota, cuenta como falla. Con `--json` los resultados salen en JSON.

---

## 6. Programación con el SDK (`hardboiled.h`)

`hardboiled.h` se genera a partir de la placa (`hardboiled gen-header` lo imprime) y ofrece las macros
de cada registro (`LEDS`, `UART_STATUS`, `TIMER_RELOAD`…) y funciones `static inline` para la placa por
defecto:

```c
#include "hardboiled.h"

// --- LEDs y switches ---
void     led_set(uint32_t mask);           // todos los LEDs (un bit por LED)
uint32_t led_get(void);
void     led_on(unsigned int index);       // también led_off() y led_toggle()
uint32_t switch_get(void);                 // los 4 switches
int      switch_read(unsigned int index);  // un switch: 0 o 1

// --- Botones ---
uint32_t buttons_get(void);                // botones presionados
int      button_read(unsigned int index);
void     button_irq_enable(uint32_t mask); // también button_irq_disable()
uint32_t buttons_pending(void);            // flancos detectados (en la ISR)
void     buttons_clear(uint32_t mask);

// --- Display de 7 segmentos ---
void    seg_show_dec(uint32_t value);
void    seg_show_hex(uint32_t value);
void    seg_set_digit(unsigned int index, uint8_t segments);
uint8_t seg_pattern(unsigned int digit);   // el dibujo de una cifra
void    seg_clear(void);

// --- UART ---
void uart_putc(char c);
void uart_puts(const char *text);
void uart_puthex(uint32_t value);
int  uart_available(void);                 // 1 si hay un byte recibido
char uart_getc(void);                      // espera hasta que llegue un byte
int  uart_gets(char *buffer, int size);    // lee hasta fin de línea
void uart_rx_irq(int enabled);             // IRQ mientras haya bytes recibidos

// --- Timer ---
void timer_start(uint32_t period_cycles, int with_irq);
void timer_stop(void);
int  timer_expired(void);                  // sondeo: ¿venció?
void timer_clear(void);

// --- Interrupciones ---
void attach_irq(unsigned int line, irq_handler_t handler);  // registra el handler y habilita la línea
void detach_irq(unsigned int line);
void interrupts_enable(void);              // habilitador global (también interrupts_disable())
void wait_for_interrupt(void);             // wfi: espera la próxima interrupción
```

### Ejemplo de Programa Bare-Metal

```c
#include "hardboiled.h"

static volatile uint32_t ticks = 0;

static void al_vencer_el_timer(void)
{
    timer_clear();
    ticks++;
    led_set(ticks);
    seg_show_hex(ticks);
}

int main(void)
{
    uart_puts("Iniciando...\n");
    attach_irq(IRQ_TIMER0, al_vencer_el_timer);
    timer_start(50000, 1);                 /* vence cada 50 000 ciclos y pide la IRQ 0 */
    interrupts_enable();

    while (ticks < 16) {
        if (button_read(0)) {
            uart_puts("Botón 0 presionado\n");
        }
        wait_for_interrupt();
    }
    timer_stop();
    return 0;
}
```

Cuando una IRQ habilitada está pendiente, la CPU guarda el PC y los registros que el ABI no preserva en
un marco de la pila, salta a `__vector_table[línea]` (en `crt0.s`), que llama al handler, y al `mret`
final restaura el marco. Por defecto no hay anidamiento; la sección `[pic]` de `board.toml` fija
prioridades y lo habilita.

---

## 7. Catálogo de Trampas y Diagnóstico de Errores

Una trampa detiene el programa con un mensaje, una pista y la línea donde ocurrió:

| Trampa | Disparador | Causa frecuente |
| :--- | :--- | :--- |
| `null-pointer` | Acceso a `0x0000_0000`–`0x0000_FFFF` | Puntero nulo o sin inicializar; una función devolvió NULL y no se verificó. |
| `flash-write` | Escritura en la Flash | Modificar un literal de cadena o una variable `const` (usá un `char[]`). |
| `unmapped` | Acceso fuera de las regiones de memoria | Puntero sin inicializar, índice fuera de rango o aritmética de punteros. |
| `bad-jump` | Salto fuera del código (por ejemplo, a la SRAM) | Puntero a función corrupto, o un buffer overflow pisó el `ra` guardado en la pila. |
| `stack-overflow` | `sp` por debajo del fin de `.bss` | Recursión sin caso base o un arreglo local demasiado grande; el mensaje nombra la global que pisaría. |
| `misaligned` | `lw`/`sw` a una dirección no múltiplo de 4 (`lh`/`sh`: de 2) | Un `int *` que apunta dentro de un `char[]`. |
| `mmio` | Registro MMIO inexistente o de sólo lectura | Una dirección escrita a mano en lugar de las macros de `hardboiled.h`. |
| `wfi-deadlock` | `wfi` sin ninguna interrupción que pueda despertar la CPU | Falta `attach_irq()`, `interrupts_enable()` o activar la IRQ del periférico. |
| `vector` | Interrupción sin tabla de vectores | Programa enlazado sin `crt0.s` ni `hardboiled.ld` (compilá con `hardboiled build`). |
| `isr-stack` | Una ISR devolvió `sp` distinto | Una ISR escrita en ensamblador que no restauró la pila. |
| `exception` | Instrucción ilegal | Salto a datos o programa compilado para otra arquitectura (`--march`). |

Además hay **avisos**, que no detienen el programa salvo que se configure así en `[board]`: `div0`
(división o resto por cero), `uninit` (lectura de una variable sin inicializar) y `limit` (se agotó la
cuota de instrucciones; F5 continúa).

Para la explicación completa (causas típicas y cómo encontrarlas con el depurador):
```bash
hardboiled explain                 # lista los tipos
hardboiled explain null-pointer
hardboiled explain stack-overflow
```

---

## 8. Tutoriales y Ejemplos Integrados

### Tutorial Interactivo

Siete lecciones que se corrigen solas: LEDs, switches, UART, timer por sondeo, interrupciones, botones
con IRQ y un programa con tres errores para cazar con el depurador:

```bash
hardboiled tutorial                  # lista las lecciones
hardboiled tutorial start 1          # copia leccion.md, main.c y casos.toml a leccion-01-leds/
hardboiled run leccion-01-leds/main.c
hardboiled tutorial check 1          # compila tu main.c y corre los casos de prueba
```

### Galería de Ejemplos

```bash
hardboiled examples                  # lista los ejemplos con su descripción
hardboiled examples show errores     # imprime un ejemplo
hardboiled examples copy hola leds   # copia los fuentes al directorio actual
hardboiled demo                      # compila y abre la demo interactiva
hardboiled demo interrupciones       # cualquier ejemplo, con las opciones de run
```

Ejemplos: `hola`, `leds`, `switches`, `botones`, `display`, `eco`, `interrupciones`, `errores`
(catálogo de trampas elegidas con los switches) y `demo`. `hardboiled demo` es además una buena prueba
de humo después de instalar.

---

## 9. Configuración del Hardware (`board.toml`)

Si existe `./board.toml` se usa como placa; si no, la placa por defecto del paquete.
`hardboiled board init` la copia al directorio actual para editarla, `hardboiled board show` la
imprime y `hardboiled validate [board.toml]` la valida (regiones alineadas y sin superposición,
periféricos dentro del espacio MMIO, líneas de IRQ únicas). Un extracto de la placa por defecto:

```toml
[board]
name = "lab-rv32-basics"
arch = "riscv32"
isa = "rv32i"                 # rv32i, rv32im, rv32ic o rv32imc
max_instructions = 5_000_000
clock_hz = 1_000_000          # opcional: acompasa la emulación al reloj real

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
name = "uart0"
type = "uart"
offset = "0x10"
irq_line = 1

[[peripherals]]
name = "timer0"
type = "timer"
offset = "0x20"
irq_line = 0

[pic]
priorities = [1, 0, 2, 3, 4, 5, 6, 7]  # prioridad de cada línea (menor = más urgente)
nesting = true                         # una IRQ más urgente interrumpe a la ISR en curso
```

Los periféricos son una lista `[[peripherals]]` con `name`, `type` y `offset` (más los campos de cada
tipo): `gpio_out`, `gpio_in`, `gpio_irq` (botones), `uart`, `timer`, `sevenseg` (con `digits`), `gpio`
(puerto bidireccional) y `adc`. El primer periférico de cada tipo usa los nombres clásicos
(`LEDS`/`led_set()`, `TIMER_CTRL`/`timer_start()`…) y los siguientes, su nombre (`BARRA`/
`barra_set()`). En `[board]` también se configuran los avisos (`div_by_zero`, `uninitialized`:
`"warn"`, `"break"` u `"off"`), `stack_guard` y `misaligned`.
