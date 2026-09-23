# Trampas y avisos de hardboiled

Qué significa cada error que detecta la placa, por qué suele pasar y cómo
encontrarlo con el depurador. Cada sección se puede leer desde la terminal con
`hardboiled explain <tipo>`.

<a id="null-pointer"></a>
## Puntero nulo (`null-pointer`)

Se leyó o escribió en una dirección entre `0x0` y `0xFFFF`: casi siempre, un
puntero que vale `NULL` (o `NULL` más un desplazamiento, como `p->campo`).

Causas típicas:

- un puntero declarado y nunca inicializado (en la pila puede valer 0);
- una función que devuelve `NULL` para indicar error y no se lo verificó;
- recorrer una lista enlazada hasta pasarse del último nodo.

Cómo encontrarlo: en la pantalla de la trampa, la pila de llamadas muestra quién
usó el puntero. En la pestaña **Variables** fijate qué puntero vale `NULL`;
con `F8` volvés al paso anterior y con un **watchpoint** (`w`) sobre el puntero
ves dónde recibió ese valor.

<a id="flash-write"></a>
## Escritura en Flash (`flash-write`)

La Flash (`0x0001_0000`–`0x0001_FFFF`) guarda el código y las constantes y es
de sólo lectura. Intentar escribirla suele ser:

- modificar un literal de cadena: `char *s = "hola"; s[0] = 'H';` — el
  literal vive en Flash; usá `char s[] = "hola";` para tener una copia en SRAM;
- escribir a través de un puntero a `const` convertido a no `const`;
- un puntero que apunta a código por error.

<a id="unmapped"></a>
## Memoria no mapeada (`unmapped`)

La dirección no pertenece a la Flash, la SRAM ni el espacio de periféricos.
Suele ser un puntero sin inicializar (con basura), un índice de arreglo muy
fuera de rango o aritmética de punteros equivocada (sumar bytes a un `int *`).

<a id="bad-jump"></a>
## Salto a una zona sin código (`bad-jump`)

El programa saltó a una dirección que no es código: la SRAM no es ejecutable y
fuera de la Flash no hay instrucciones. Casi siempre es:

- un **puntero a función** sin inicializar o corrupto;
- una **dirección de retorno pisada**: un arreglo local escrito fuera de sus
  límites (buffer overflow) pisa el `ra` guardado en la pila y el `return`
  salta a cualquier lado. La pestaña **Pila** muestra dónde está cada `ra`
  guardado y el paso atrás (`F8`) permite ver quién lo escribió.

<a id="stack-overflow"></a>
## Desborde de pila (`stack-overflow`)

La pila creció hasta invadir las variables globales (o salió de la SRAM). Cada
llamada ocupa lugar en la pila: parámetros, variables locales, `ra` y `s0`.

- **Recursión sin caso base** (o con uno que nunca se cumple): la pila de
  llamadas muestra la misma función repetida cientos de veces.
- **Arreglos locales enormes**: `int buffer[20000];` dentro de una función no
  entra en 64 KB de SRAM; declaralo `static` o global.

<a id="misaligned"></a>
## Acceso desalineado (`misaligned`)

Un `lw`/`sw` (4 bytes) necesita una dirección múltiplo de 4 y un `lh`/`sh`,
múltiplo de 2. Suele pasar al convertir un `char *` a `int *` y leer "a la
mitad" de un buffer, o con estructuras empaquetadas. Copiá los bytes con un
bucle (o `memcpy`) en lugar de convertir el puntero.

<a id="mmio"></a>
## Acceso MMIO inválido (`mmio`)

Se accedió al espacio de periféricos (`0x4000_0000`) en un offset donde no hay
ningún registro, se escribió un registro de sólo lectura (como `SWITCHES`) o se
hizo un acceso desalineado. Usá las macros y funciones de `hardboiled.h` en
lugar de direcciones escritas a mano; si la placa es propia, generá el SDK con
`hardboiled gen-header`.

<a id="wfi-deadlock"></a>
## wfi sin nada que despierte a la CPU (`wfi-deadlock`)

`wait_for_interrupt()` duerme la CPU hasta que llegue una interrupción, pero
ninguna puede llegar: falta `attach_irq()` para esa línea, falta
`interrupts_enable()` o el periférico no tiene su interrupción activada (por
ejemplo `timer_start(periodo, 1)` con el 1, o `uart_rx_irq(1)`).

<a id="vector"></a>
## Vector de interrupción inválido (`vector`)

Llegó una interrupción pero la tabla de vectores falta o apunta fuera del
código. Pasa si el programa no se enlazó con el `crt0.s` y el `hardboiled.ld`
del runtime: compilá con `hardboiled build` o `hardboiled run archivo.c`.

<a id="isr-stack"></a>
## Pila desbalanceada al volver de una interrupción (`isr-stack`)

Al ejecutar `mret`, `sp` no quedó donde estaba al entrar a la interrupción, o se
ejecutó `mret` fuera de una. Suele ser ensamblador escrito a mano que modifica
`sp` sin restaurarlo. Las ISR escritas en C y registradas con `attach_irq()` no
tienen este problema.

<a id="exception"></a>
## Excepción de la CPU (`exception`)

La CPU encontró una instrucción que no sabe ejecutar: normalmente porque el
programa saltó a datos que no son código, o se compiló para otra arquitectura.
Revisá la instrucción que falló en la pantalla de la trampa y compilá con
`--march rv32i` (o `rv32im`/`rv32imc`).

<a id="limit"></a>
## Límite de instrucciones (`limit`)

No es un error: el programa ejecutó `max_instructions` instrucciones. Si es un
bucle infinito, la pausa muestra dónde está dando vueltas; si el programa sólo
es largo, `F5` continúa otro tanto (o `--max-instructions` en `--headless`).

<a id="div0"></a>
## División por cero (`div0`, aviso)

RISC-V no genera una excepción al dividir por cero: con la extensión M el
cociente queda en −1 y el resto es el dividendo; con división por software, el
resultado depende de la biblioteca. El programa sigue con un valor sin sentido.
Verificá el divisor antes de dividir. Con `div_by_zero = "break"` en `[board]`
la ejecución se detiene en la división.

<a id="uninit"></a>
## Lectura sin inicializar (`uninit`, aviso)

Se leyó una variable local (o memoria de la pila) antes de asignarle un valor:
en C su contenido es indefinido, y suele ser lo que dejó una llamada anterior.
Inicializá la variable al declararla. Con `uninitialized = "break"` en
`[board]` la ejecución se detiene en la lectura.
