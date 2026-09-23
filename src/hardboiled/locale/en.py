"""English messages. Keys are the original Spanish texts (see hardboiled.i18n)."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # ------------------------------------------------------------ cli/run.py
    "traza: {rows} instrucciones en {path}{cut}": "trace: {rows} instructions in {path}{cut}",
    " (se cortó al llegar a --trace-limit {limit})": " (cut at --trace-limit {limit})",
    "sin información de línea": "no line information",
    "TRAP: {message}": "TRAP: {message}",
    "aviso: {message}": "warning: {message}",
    "en {function}() pc={pc} ({where})": "in {function}() pc={pc} ({where})",
    "LÍMITE: {message}. Con --max-instructions se puede dar más margen.": (
        "LIMIT: {message}. --max-instructions gives it more room."
    ),
    "pista: {hint}": "hint: {hint}",
    "instrucción: {text}": "instruction: {text}",
    "pila de llamadas:": "call stack:",
    " x{count} (recursión)": " x{count} (recursion)",
    # ------------------------------------------------------- core/buildinfo.py
    "el programa no tiene información de depuración de tu código (¿se compiló sin -g?): "
    "no se puede seguir línea por línea ni ver variables. `hardboiled build` ya agrega -g.": (
        "the program has no debug information for your code (was it compiled without "
        "-g?): you cannot step line by line or see variables. `hardboiled build` already "
        "adds -g."
    ),
    "el programa parece compilado con optimización ({reasons}): el paso a paso puede "
    "saltar líneas o volver atrás y algunas variables figuran como no disponibles. Para "
    "depurar conviene -O0.": (
        "the program seems to be compiled with optimization ({reasons}): stepping may skip "
        "lines or go back, and some variables show as unavailable. Use -O0 for debugging."
    ),
    "{count} variables cambian de lugar durante la función": (
        "{count} variables move around during the function"
    ),
    "funciones sin frame pointer ({names})": "functions without a frame pointer ({names})",
    "el compilador registró -O{level}": "the compiler recorded -O{level}",
    # ------------------------------------------------------------- core/cpu.py
    "división": "division",
    "resto (%)": "remainder (%)",
    "lectura": "read",
    "escritura": "write",
    "ejecución": "execution",
    "acceso": "access",
    "lectura de {what} sin inicializar: su valor es indefinido (suele ser lo que dejó "
    "una llamada anterior)": (
        "read of uninitialized {what}: its value is undefined (usually whatever a previous "
        "call left there)"
    ),
    "memoria de la pila en {address}": "stack memory at {address}",
    "M (multiplicación/división)": "M (multiplication/division)",
    "C (comprimidas)": "C (compressed)",
    "A (atómicas)": "A (atomics)",
    "F (punto flotante)": "F (floating point)",
    "D (doble precisión)": "D (double precision)",
    "{program} usa la extensión {extensions}{arch}, pero la placa es {isa}: compilá con "
    "--march {isa} o declará isa en [board] de board.toml": (
        "{program} uses the {extensions} extension{arch}, but the board is {isa}: compile "
        "with --march {isa} or set isa in [board] of board.toml"
    ),
    "el segmento en {address} ({size} bytes) no entra en Flash ni en SRAM: ¿se enlazó "
    "con el hardboiled.ld del runtime?": (
        "the segment at {address} ({size} bytes) fits neither in Flash nor in SRAM: was it "
        "linked with the runtime's hardboiled.ld?"
    ),
    "la ejecución se detuvo en {pc} sin motivo conocido": (
        "execution stopped at {pc} for no known reason"
    ),
    "invadió las variables globales (el fin de .bss es {end}){target}": (
        "ran into the global variables (.bss ends at {end}){target}"
    ),
    "quedó por debajo del inicio de la SRAM ({base})": "went below the start of SRAM ({base})",
    "stack overflow: sp = {sp} {where}. ¿Recursión sin caso base o arreglos locales "
    "enormes?": "stack overflow: sp = {sp} {where}. Recursion without a base case or huge "
    "local arrays?",
    ": pisaría la variable `{name}`": ": it would overwrite the variable `{name}`",
    " y quedó fuera de la SRAM": " and left the SRAM",
    "el resultado no está definido (depende de la biblioteca)": (
        "the result is undefined (it depends on the library)"
    ),
    "el cociente queda en -1": "the quotient becomes -1",
    "el resto es el dividendo": "the remainder is the dividend",
    "{operation} por cero: RISC-V no genera una excepción; {result} y el programa sigue "
    "como si nada": (
        "{operation} by zero: RISC-V raises no exception; {result} and the program carries "
        "on as if nothing happened"
    ),
    "media palabra (2 bytes)": "halfword (2 bytes)",
    "palabra (4 bytes)": "word (4 bytes)",
    "acceso desalineado: {kind} de una {unit} en {address}, que no es múltiplo de {size}. "
    "¿Un puntero a int que apunta dentro de un char[]?": (
        "misaligned access: {kind} of a {unit} at {address}, which is not a multiple of "
        "{size}. An int pointer pointing inside a char[]?"
    ),
    "acceso MMIO inválido: {fault}": "invalid MMIO access: {fault}",
    "desreferencia de puntero nulo: {kind} en {address}": (
        "null pointer dereference: {kind} at {address}"
    ),
    "sólo se pueden vigilar variables en la SRAM": "only variables in SRAM can be watched",
    "se alcanzó el límite de {count} instrucciones (¿un bucle infinito?)": (
        "reached the limit of {count} instructions (an infinite loop?)"
    ),
    "llegó la IRQ {line} pero el binario no define __vector_table": (
        "IRQ {line} arrived but the binary does not define __vector_table"
    ),
    "IRQ {line}: el vector apunta a {handler}, fuera de Flash": (
        "IRQ {line}: the vector points to {handler}, outside Flash"
    ),
    "mret ejecutado fuera de una rutina de interrupción": (
        "mret executed outside an interrupt service routine"
    ),
    "la ISR dejó la pila desbalanceada: sp = {sp}, se esperaba {expected}": (
        "the ISR left the stack unbalanced: sp = {sp}, expected {expected}"
    ),
    "wfi: la CPU se durmió sin ninguna interrupción habilitada que pueda despertarla "
    "(deadlock)": "wfi: the CPU went to sleep with no enabled interrupt that can wake it "
    "(deadlock)",
    "ejecución pausada": "execution paused",
    "ejecución pausada (esperando datos)": "execution paused (waiting for input)",
    "excepción de la CPU en {pc}: {error} (¿instrucción ilegal o acceso a memoria "
    "desalineado?)": "CPU exception at {pc}: {error} (illegal instruction or misaligned "
    "memory access?)",
    "salto a {address}, en {where}": "jump to {address}, in {where}",
    "la SRAM (no es ejecutable)": "SRAM (not executable)",
    "una zona sin código": "an area without code",
    "escritura en Flash (memoria de sólo lectura) en {address}": (
        "write to Flash (read-only memory) at {address}"
    ),
    "{kind} en memoria no mapeada: {address}": "{kind} of unmapped memory: {address}",
    "programa terminado ({code})": "program finished ({code})",
    # -------------------------------------------------------- core/debugger.py
    "breakpoint condicional: {detail}": "conditional breakpoint: {detail}",
    "pasada {hits}": "hit {hits}",
    "cambió su contenido": "its contents changed",
    " (escrito en {file}:{line})": " (written at {file}:{line})",
    "watchpoint eliminado al salir de su función: {names}": (
        "watchpoint removed when its function returned: {names}"
    ),
    "si {expression}": "if {expression}",
    "desde la pasada {hits}": "from hit {hits}",
    "la cantidad de pasadas debe ser 1 o más": "the hit count must be 1 or more",
    "{expression} es verdadera": "{expression} is true",
    "no hay código ejecutable en {file}:{line} ni después": (
        "there is no executable code at {file}:{line} or after it"
    ),
    "indicá el archivo fuente del breakpoint": "specify the source file of the breakpoint",
    "el binario no tiene información de líneas de {file}": (
        "the binary has no line information for {file}"
    ),
    "interrupción IRQ {line}": "interrupt IRQ {line}",
    "{register} guardado": "saved {register}",
    "{expression} no es una variable en memoria: no se puede vigilar": (
        "{expression} is not a variable in memory: it cannot be watched"
    ),
    "{expression} no tiene tamaño conocido": "{expression} has no known size",
    "no hay una función llamadora a la que volver": "there is no calling function to return to",
    "fin de la interrupción ({function})": "end of the interrupt ({function})",
    "{function} devolvió a0 = {value} ({hex})": "{function} returned a0 = {value} ({hex})",
    "no se pudo evaluar la condición: {error}": "could not evaluate the condition: {error}",
    "IRQ {line}: pc interrumpido": "IRQ {line}: interrupted pc",
    "condición inválida: {error}": "invalid condition: {error}",
    "IRQ: {register} guardado": "IRQ: saved {register}",
    "IRQ: relleno (alineación a 16)": "IRQ: padding (16-byte alignment)",
    # ----------------------------------------------------------- core/hints.py
    "¿El puntero se inicializó? ¿Una función devolvió NULL y no se verificó?": (
        "Was the pointer initialized? Did a function return NULL without it being checked?"
    ),
    "¿Se modificó un literal de cadena o una variable const? Usá un char[].": (
        "Was a string literal or a const variable modified? Use a char[]."
    ),
    "¿Puntero sin inicializar, índice fuera de rango o aritmética de punteros?": (
        "Uninitialized pointer, index out of range or pointer arithmetic?"
    ),
    "¿Puntero a función corrupto, o un buffer overflow pisó el ra guardado en la pila?": (
        "Corrupted function pointer, or a buffer overflow overwrote the ra saved on the stack?"
    ),
    "¿Recursión sin caso base? ¿Un arreglo local demasiado grande?": (
        "Recursion without a base case? A local array that is too large?"
    ),
    "¿Un int* que apunta dentro de un char[]? Copiá los bytes en lugar de convertir.": (
        "An int* pointing inside a char[]? Copy the bytes instead of casting."
    ),
    "Usá las macros de hardboiled.h en lugar de direcciones escritas a mano.": (
        "Use the hardboiled.h macros instead of hand-written addresses."
    ),
    "Falta attach_irq(), interrupts_enable() o activar la IRQ del periférico.": (
        "attach_irq(), interrupts_enable() or enabling the peripheral's IRQ is missing."
    ),
    "Compilá con `hardboiled build` para enlazar crt0.s y hardboiled.ld.": (
        "Compile with `hardboiled build` to link crt0.s and hardboiled.ld."
    ),
    "Una ISR escrita en ensamblador dejó sp distinto de como lo encontró.": (
        "An ISR written in assembly left sp different from how it found it."
    ),
    "Instrucción desconocida: ¿salto a datos o compilado para otra arquitectura?": (
        "Unknown instruction: a jump into data, or compiled for another architecture?"
    ),
    "Si es un bucle infinito, la pausa muestra dónde; si no, F5 continúa.": (
        "If it is an infinite loop, the pause shows where; otherwise F5 continues."
    ),
    "Verificá que el divisor no sea cero antes de dividir.": (
        "Check that the divisor is not zero before dividing."
    ),
    "Inicializá la variable al declararla.": "Initialize the variable when you declare it.",
    # --------------------------------------------------------- periféricos/PIC
    "registro inexistente": "no such register",
    "ACTIVE es de sólo lectura": "ACTIVE is read-only",
    "STATE es de sólo lectura": "STATE is read-only",
    "COUNT es de sólo lectura": "COUNT is read-only",
    "los switches son de sólo lectura": "the switches are read-only",
    "registro de sólo lectura": "read-only register",
    "{device} no tiene el botón {pin}": "{device} has no button {pin}",
    "{device} no tiene el pin {pin}": "{device} has no pin {pin}",
    "no hay ningún periférico en el offset MMIO {offset}": "no peripheral at MMIO offset {offset}",
    "tamaño de acceso no soportado ({size} bytes) en {offset}": (
        "unsupported access size ({size} bytes) at {offset}"
    ),
    "acceso desalineado de {size} bytes en {offset}": "misaligned {size}-byte access at {offset}",
    # ---------------------------------------------------------- core/runner.py
    "reset": "reset",
    "; no se pudieron reubicar: {points}": "; could not be relocated: {points}",
    "paso atrás ({count} disponibles; la UART no se deshace)": (
        "step back ({count} available; UART output is not undone)"
    ),
    "el espacio MMIO (leerlo tendría efectos)": "the MMIO space (reading it has side effects)",
    "una zona sin memoria": "an area without memory",
    "{address} está en {region}": "{address} is in {region}",
    "programa recargado ({count} puntos conservados){note}": (
        "program reloaded ({count} points kept){note}"
    ),
    "no se pudieron restaurar: {points} (código cambiado)": (
        "could not be restored: {points} (the code changed)"
    ),
    "inicio de main()": "start of main()",
    "no hay pasos anteriores para deshacer": "there are no previous steps to undo",
    "breakpoint": "breakpoint",
    "step": "step",
    "placa reiniciada": "board reset",
    "cambió el código: recompilando…": "the code changed: recompiling…",
    "no se recargó {path}: {error}": "{path} was not reloaded: {error}",
    "no se recargó: {error}": "not reloaded: {error}",
    "{message}. Usá Reset para volver a empezar": "{message}. Use Reset to start over",
    " o F8 para volver atrás.": " or F8 to step back.",
    "la placa no tiene botones": "the board has no buttons",
    "la placa no tiene UART": "the board has no UART",
    "la placa no tiene switches": "the board has no switches",
    "{message}. F5 continúa otras {count} instrucciones.": (
        "{message}. F5 continues for another {count} instructions."
    ),
    # --------------------------------------------------------------- ui/tui.py
    "Continue": "Continue",
    "Pause": "Pause",
    "Breakpoint": "Breakpoint",
    "Step Over": "Step Over",
    "Step Into": "Step Into",
    "Step Out": "Step Out",
    "Stepi": "Stepi",
    "Atrás": "Back",
    "Hasta cursor": "To cursor",
    "Watch": "Watch",
    "ASM": "ASM",
    "Perfil": "Profile",
    "Archivos": "Files",
    "Buscar": "Search",
    "Ayuda": "Help",
    "Reset": "Reset",
    "Salir": "Quit",
    "sin límite (+/- para fijarlo, = alterna)": "unlimited (+/- to set it, = toggles)",
    "Código": "Code",
    "Consola UART": "UART console",
    "Placa": "Board",
    "Placa · reloj {clock}": "Board · clock {clock}",
    "Consola UART ({count} bytes recibidos sin leer)": (
        "UART console ({count} bytes received, unread)"
    ),
    "registros en formato: {mode}": "registers shown as: {mode}",
    "cantidad de pasadas inválida: #{count}": "invalid hit count: #{count}",
    "cargando…": "loading…",
    "acciones desconocidas en [keys]: {actions} (ver ? para la lista)": (
        "unknown actions in [keys]: {actions} (see ? for the list)"
    ),
    "ciclos={cycles}": "cycles={cycles}",
    "{frame}: sin código fuente": "{frame}: no source code",
    "Breakpoint condicional en la línea {line}:": "Conditional breakpoint at line {line}:",
    "Buscar en el código:": "Search the code:",
    "no se encontró {text}": "{text} not found",
    "Ir a la línea:": "Go to line:",
    "número": "number",
    "el programa no tiene archivos fuente con información de depuración": (
        "the program has no source files with debug information"
    ),
    "mapa de calor oculto": "heat map hidden",
    "Vigilar una expresión (detiene cuando cambia):": (
        "Watch an expression (stops when it changes):"
    ),
    "▶ ejecutando ": "▶ running ",
    "  (F6 pausa)": "  (F6 pauses)",
    "▶ ejecutando…  (F6 pausa)": "▶ running…  (F6 pauses)",
    "main() devolvió {code}": "main() returned {code}",
    "Programa terminado": "Program finished",
    "Aviso": "Warning",
    "Una expresión C detiene sólo si es verdadera; #N detiene desde la pasada N. Vacío: "
    "breakpoint común.": (
        "A C expression stops only when it is true; #N stops from the Nth hit on. Empty: "
        "plain breakpoint."
    ),
    "F3 siguiente, Shift+F3 anterior; vacío quita el resaltado.": (
        "F3 next, Shift+F3 previous; empty clears the highlight."
    ),
    "línea inválida: {text}": "invalid line: {text}",
    "{count} instrucciones desde el reset": "{count} instructions since reset",
    "Perfil (h lo oculta)": "Profile (h hides it)",
    "La misma expresión otra vez quita el watchpoint. Los de variables locales se eliminan "
    "al terminar su función.": (
        "The same expression again removes the watchpoint. Watchpoints on local variables are "
        "removed when their function returns."
    ),
    "escribí y Enter para enviar por la UART (Esc vuelve al código)": (
        "type and press Enter to send through the UART (Esc goes back to the code)"
    ),
    "Variables": "Variables",
    "Registros": "Registers",
    "Pila": "Stack",
    "Puntos": "Points",
    "Memoria": "Memory",
    # ------------------------------------------------------------- ui/widgets
    "Llamadas": "Calls",
    "Quitar": "Remove",
    "(sin breakpoints ni watchpoints)": "(no breakpoints or watchpoints)",
    "(sin código fuente para la ubicación actual)": "(no source code for the current location)",
    "no se pudo abrir {path}: {error}": "could not open {path}: {error}",
    "Desensamblado": "Disassembly",
    "Cancelar": "Cancel",
    "Abrir archivo fuente (Enter abre, Esc cancela):": (
        "Open source file (Enter opens, Esc cancels):"
    ),
    "pulsaciones: {presses}, flancos pendientes: {pending}": (
        "presses: {presses}, pending edges: {pending}"
    ),
    "detenido": "stopped",
    "  vencimientos: {count}": "  expirations: {count}",
    "período {cycles}": "period {cycles}",
    "  faltan {count}": "  {count} to go",
    "Continue: corre hasta un breakpoint, una trampa o el fin": (
        "Continue: run until a breakpoint, a trap or the end"
    ),
    "Pausa una ejecución en curso": "Pause a running program",
    "Pone/quita un breakpoint en la línea del cursor": "Set/clear a breakpoint at the cursor line",
    "Breakpoint condicional (`i == 3`, `#5`)": "Conditional breakpoint (`i == 3`, `#5`)",
    "Step Over: siguiente línea sin entrar en funciones": (
        "Step Over: next line without entering functions"
    ),
    "Step Into: siguiente línea, entrando en funciones": "Step Into: next line, entering functions",
    "Step Out: termina la función actual": "Step Out: finish the current function",
    "Stepi: una instrucción de máquina": "Stepi: one machine instruction",
    "Paso atrás: deshace el último paso": "Step back: undo the last step",
    "Ejecuta hasta la línea del cursor": "Run to the cursor line",
    "Watchpoint: detiene cuando cambia una expresión": (
        "Watchpoint: stop when an expression changes"
    ),
    "Muestra u oculta el desensamblado": "Show or hide the disassembly",
    "Mapa de calor: instrucciones ejecutadas por línea": "Heat map: instructions executed per line",
    "Cambia el formato de los registros": "Change the register format",
    "Abre otro archivo fuente": "Open another source file",
    "Busca en el código": "Search the code",
    "Siguiente coincidencia": "Next match",
    "Coincidencia anterior": "Previous match",
    "Va a una línea": "Go to a line",
    "Duplica la frecuencia del reloj de la CPU": "Double the CPU clock frequency",
    "Reduce el reloj a la mitad (cámara lenta)": "Halve the clock (slow motion)",
    "Alterna entre reloj fijo y sin límite": "Toggle between a fixed and an unlimited clock",
    "Reinicia la placa": "Reset the board",
    "Esta ayuda": "This help",
    "breakpoint condicional": "conditional breakpoint",
    "línea (o instrucción) en ejecución": "line (or instruction) being executed",
    "línea del marco elegido en Llamadas": "line of the frame chosen in Calls",
    "línea donde ocurrió una trampa": "line where a trap happened",
    "watchpoint (pestaña Puntos)": "watchpoint (Points tab)",
    "Cerrar": "Close",
    "Conmuta un switch": "Toggle a switch",
    "Flash (R X): código, constantes, imagen de .data": "Flash (R X): code, constants, .data image",
    "SRAM (R W): .data, .bss, heap y pila (crece hacia abajo)": (
        "SRAM (R W): .data, .bss, heap and stack (grows downwards)"
    ),
    "MMIO: periféricos": "MMIO: peripherals",
    "zona de trampa: acceder es un puntero nulo": "trap zone: accessing it is a null pointer",
    "Ayuda de hardboiled (Esc cierra)": "hardboiled help (Esc closes)",
    "Marcadores": "Markers",
    "Mapa de memoria": "Memory map",
    "Anterior": "Previous",
    "Siguiente": "Next",
    "dirección, símbolo o expresión (&results, 0x20000000…)": (
        "address, symbol or expression (&results, 0x20000000…)"
    ),
    "Pila (direcciones altas arriba)": "Stack (high addresses on top)",
    "(sp fuera de la SRAM)": "(sp outside SRAM)",
    "con signo": "signed",
    "sin signo": "unsigned",
    "símbolo": "symbol",
    "Registros ({mode}; x cambia)": "Registers ({mode}; x changes)",
    "✖ TRAMPA: la ejecución se abortó": "✖ TRAP: execution aborted",
    "Dónde": "Where",
    "Esc cierra este panel: variables, registros y memoria quedan como estaban al fallar. "
    "F8 vuelve al paso anterior; r reinicia la placa.": (
        "Esc closes this panel: variables, registers and memory stay as they were when it "
        "failed. F8 goes back one step; r resets the board."
    ),
    "Instrucción que falló": "Failing instruction",
    "Pista": "Hint",
    "Pila de llamadas": "Call stack",
    "Más detalles: hardboiled explain {kind}": "More details: hardboiled explain {kind}",
    "dirección involucrada: {address}": "address involved: {address}",
    "Locales": "Locals",
    "Locales de {function}": "Locals of {function}",
    "Globales": "Globals",
    "(ninguna)": "(none)",
    # ----------------------------------------------- expresiones y variables
    "<no disponible>": "<not available>",
    "<sin acceso a {address}>": "<no access to {address}>",
    "símbolo inesperado en la posición {position}: {text}": (
        "unexpected symbol at position {position}: {text}"
    ),
    "la expresión está vacía": "the expression is empty",
    "sobra texto después de la posición {position}: {text}": (
        "extra text after position {position}: {text}"
    ),
    "no se puede usar un {type} como número": "a {type} cannot be used as a number",
    "no se puede leer la memoria en {address}": "cannot read memory at {address}",
    "se esperaba '{token}'": "expected '{token}'",
    "división por cero en la expresión": "division by zero in the expression",
    "& necesita una variable en memoria": "& needs a variable in memory",
    "sólo se puede desreferenciar un puntero": "only a pointer can be dereferenced",
    "no se puede desreferenciar un {type}": "a {type} cannot be dereferenced",
    "{type} no se puede indexar": "{type} cannot be indexed",
    "se esperaba un nombre de campo después de '{token}'": "expected a field name after '{token}'",
    "{type} no tiene campos": "{type} has no fields",
    "{name} es un campo de bits: no tiene dirección": "{name} is a bit field: it has no address",
    "{type} no tiene un campo {name}": "{type} has no field {name}",
    "la expresión termina antes de tiempo": "the expression ends too early",
    "no se esperaba '{token}'": "unexpected '{token}'",
    "los registros sólo están disponibles con el programa detenido": (
        "registers are only available while the program is stopped"
    ),
    "registro desconocido: ${name}": "unknown register: ${name}",
    "${name} no se conoce en este marco": "${name} is not known in this frame",
    "no hay ninguna variable {name} visible aquí": "there is no variable {name} visible here",
    "la ubicación de {name} no está disponible": "the location of {name} is not available",
}
