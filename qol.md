# hardboiled — mejoras de calidad de vida (QoL)

Propuestas surgidas de implementar y usar la versión 1.0.0. Cada mejora indica
**impacto** pedagógico/práctico (🔴 alto · 🟡 medio · 🟢 bajo) y **esfuerzo**
estimado (S: horas · M: 1-2 días · L: más).

---

## A. Depuración

1. **Inspección de variables (locales y globales)** — 🔴 · L
   Leer `.debug_info` (DIEs de variables, tipos y `DW_AT_location`) y mostrar
   un panel "Variables" con nombre, tipo y valor. Hoy el alumno sólo ve
   registros y palabras crudas de la pila.
2. **Backtrace / pila de llamadas** — 🔴 · M
   Recorrer los marcos con `.debug_frame` (o con `s0/fp` a `-O0`) y listar
   `main → sum_squares → square` con archivo:línea. Clickear un marco muestra
   su código.
3. **Step Out (`finish`)** — 🔴 · S
   Ejecutar hasta volver al llamador: breakpoint efímero en `ra` con la misma
   condición de `sp` que ya usa Step Over.
4. **Run to cursor** — 🟡 · S
   Ejecutar hasta la línea bajo el cursor sin crear un breakpoint (reutiliza
   `Debugger.run_to` + `address_for_line`).
5. **Step de instrucción (`stepi`)** — 🟡 · S
   Avanzar una sola instrucción de máquina; imprescindible para temas de
   arquitectura y para ver `crt0.s` en detalle.
6. **Watchpoints de memoria** — 🔴 · M
   "Detener cuando cambie `results[1]`" con `UC_HOOK_MEM_WRITE` acotado a la
   dirección. Muy útil para cazar corrupciones de memoria.
7. **Breakpoints condicionales y por cantidad de pasadas** — 🟡 · M
   `i == 3` o "detener en la 5.ª pasada"; evita pulsar F5 muchas veces en
   bucles.
8. **Breakpoints persistentes entre sesiones** — 🟢 · S
   Guardarlos en `.hardboiled/breakpoints.json` junto al ELF y restaurarlos al
   abrir el mismo programa.
9. **Paso hacia atrás (historial de estados)** — 🟡 · L
   Guardar instantáneas (`uc.context_save` + SRAM + estado de periféricos) en
   cada suspensión para poder retroceder. Resuelve el clásico "me pasé de
   línea".
10. **Pantalla post-mortem de la trampa** — 🔴 · S
    Al ocurrir una trampa: resaltar la línea culpable en rojo, mostrar la
    instrucción que falló y el backtrace, y dejar todo inspeccionable antes del
    Reset.

## B. Interfaz (TUI)

11. **Vista de desensamblado mixta (C + ASM)** — 🔴 · M
    Panel conmutable que muestre las instrucciones RV32I de cada línea de C,
    con la instrucción actual resaltada (Capstone soporta RISC-V).
12. **Visor de memoria navegable** — 🟡 · M
    Hex dump con "ir a dirección/símbolo" (`&results`, `0x20000000`), con
    resaltado de los bytes que cambiaron desde la última suspensión.
13. **Registros en varios formatos** — 🟡 · S
    Alternar hexadecimal / decimal con signo / sin signo / ASCII, y mostrar el
    símbolo cuando un registro apunta a código (`ra = main+0x2c`).
14. **Pila anotada por marcos** — 🟡 · M
    Separar visualmente cada marco, etiquetar direcciones de retorno con su
    función y señalar variables locales cuando haya info DWARF.
15. **Estado en vivo mientras corre** — 🟡 · S
    Emitir cada ~200 ms un evento de progreso (ciclos, instrucciones/s, PC
    aproximado) para que Continue no parezca colgado.
16. **Selector de archivos fuente** — 🟡 · S
    Lista de los `source_files` del ELF para abrir otro `.c` y poner
    breakpoints antes de llegar a él.
17. **Búsqueda e ir a línea en el código** — 🟢 · S
    `/texto` y `:número`, como en `less`/`vim`.
18. **Pantalla de ayuda (`?`)** — 🟡 · S
    Resumen de teclas, significado de los marcadores (`●`, `▶`) y del mapa de
    memoria.
19. **Atajos configurables** — 🟢 · S
    Algunas terminales capturan F10/F11 (menú, pantalla completa); permitir
    remapear desde un archivo de configuración.
20. **Tema claro y paleta apta para daltonismo** — 🟢 · S
    Proyector del aula = tema claro; LEDs con forma además de color (● / ○ ya
    ayuda, extenderlo a switches y estados).

## C. Periféricos y placa

21. **Entrada por UART (RX)** — 🔴 · M
    Escribir en la consola de la TUI y que el firmware lo lea con
    `uart_getc()`, con IRQ opcional de "dato recibido". Habilita programas
    interactivos.
22. **Botones pulsadores con interrupción** — 🔴 · M
    Periférico `gpio_irq` (flanco de subida/bajada) para practicar ISRs sin
    depender sólo del timer. Hoy sólo los timers generan IRQs.
23. **Display de 7 segmentos** — 🟡 · S
    Periférico clásico de cátedra; se dibuja fácil en la TUI.
24. **Generar `hardboiled.h` desde `board.toml`** — 🔴 · S
    `hardboiled gen-header board.toml` para que los offsets del SDK nunca
    queden desincronizados de una placa personalizada.
25. **Vista viva del timer** — 🟢 · S
    Mostrar `COUNT` y la cantidad de vencimientos en cada suspensión (hoy sólo
    se actualiza al escribir CTRL/RELOAD).
26. **Velocidad de reloj ajustable en la TUI** — 🟡 · S
    Controles `+`/`-` para cambiar `clock_hz` en caliente (cámara lenta para
    ver parpadeos, máxima velocidad para cálculos).
27. **Prioridades y anidamiento de interrupciones configurables** — 🟢 · M
    Hoy la línea más baja gana y no hay anidamiento; exponerlo en
    `board.toml` para cursos avanzados.
28. **Guardia de pila contra `.bss`/heap** — 🔴 · S
    Detectar también cuando `sp` baja de `_end` (pisando globales), no sólo
    cuando sale de la SRAM: es el overflow que los alumnos realmente sufren.

## D. Diagnóstico pedagógico

29. **Detección de lecturas no inicializadas** — 🔴 · L
    Memoria "sombra" que marque bytes de pila/SRAM nunca escritos y avise al
    leerlos (el error más común en C de principiantes).
30. **Sugerencias en cada trampa** — 🟡 · S
    Agregar una pista contextual: "¿inicializaste el puntero?", "¿el arreglo
    tiene índice fuera de rango?", con enlace a la sección del apunte.
31. **Aviso de binario sin `-g` o con optimización** — 🟡 · S
    Si no hay líneas DWARF o se detecta `-O2`, explicar por qué el paso a paso
    "salta" y cómo compilar.
32. **Aviso de división por cero** — 🟢 · S
    RV32I no la atrapa y `__divsi3` devuelve un valor silencioso; interceptar
    la llamada y advertir.
33. **Explicación de acceso desalineado** — 🟢 · S
    Hoy cae en "excepción de CPU"; distinguirla y explicar la alineación.
34. **Límite de instrucciones no fatal** — 🟡 · S
    Al agotar la cuota, suspender (no abortar) y ofrecer "continuar con otro
    millón": no todo programa largo es un bucle infinito.

## E. Toolchain y flujo de trabajo

35. **Subcomando `hardboiled build`** — 🔴 · M
    Compilar un `.c` con los flags correctos detectando `riscv*-gcc` o usando
    `ziglang`; elimina la barrera de la línea de compilación larga.
36. **Subcomando `hardboiled new`** — 🟡 · S
    Crear un proyecto de ejemplo (`main.c`, `Makefile`, `board.toml`) listo
    para compilar.
37. **Recarga automática al recompilar** — 🟡 · M
    Vigilar el ELF: si cambia, recargar conservando breakpoints (reubicados por
    archivo:línea).
38. **Excluir la info DWARF de bibliotecas** — 🟢 · S
    Saltear CUs sin fuente al parsear (compiler-rt suma ~0,4 s de carga y
    ~870 KB a `basic.elf`); o strip selectivo en `build.py`.
39. **Soporte de la extensión M (`rv32im`)** — 🟢 · S
    Unicorn ya la ejecuta; permitirla por configuración evitaría las llamadas a
    `__mulsi3` que ensucian el Step Into.
40. **Soporte de instrucciones comprimidas (C)** — 🟢 · M
    Usar el `size` que entrega el hook en lugar de asumir 4 bytes, para aceptar
    binarios de toolchains por defecto (`rv32imac`).

## F. CLI, automatización y evaluación

41. **Modo de prueba con salida esperada** — 🔴 · M
    `hardboiled test prog.elf --switches 5 --expect-uart salida.txt
    --expect-exit 3` para corrección automática de trabajos prácticos.
42. **Salida JSON** — 🟡 · S
    `--json` en `info` y `run --headless` (código de salida, trampa, ubicación,
    ciclos) para integrarlo con otras herramientas de la cátedra.
43. **Traza de ejecución exportable** — 🟡 · M
    `--trace traza.csv` con PC, línea y registros modificados por instrucción,
    para ejercicios de seguimiento de código.
44. **Guion de entrada para periféricos** — 🟡 · M
    Archivo que cambie switches o inyecte bytes UART en ciclos dados, para
    probar firmware de forma reproducible.
45. **Perfilado por línea/función** — 🟢 · M
    Contar instrucciones ejecutadas por línea y mostrarlo como "mapa de calor"
    en el código: ilustra costo de bucles y recursión.

## G. Rendimiento y robustez

46. **Continue más rápido** — 🟡 · M
    Sin breakpoints activos, reemplazar el hook por instrucción por hooks de
    bloque y contar instrucciones con `count` de `emu_start`; hoy cuesta
    ~0,7 µs por instrucción.
47. **Reset sin recrear Unicorn** — 🟢 · S
    Restaurar memoria y registros con un contexto guardado en lugar de
    reconstruir el motor y reescanear el código.
48. **Integración continua multiplataforma** — 🟡 · S
    GitHub Actions con Linux, macOS y Windows (WSL2) ejecutando pytest, ruff y
    mypy, para verificar RNF-01 de verdad.

## H. Documentación y pedagogía

49. **Tutorial guiado con ejercicios** — 🔴 · M
    Serie de prácticas progresivas (LED → switches → UART → timer → ISR →
    depuración de trampas) usando los fixtures como base.
50. **Mensajes en inglés (i18n)** — 🟢 · M
    Externalizar los textos de trampas y UI para ofrecer español e inglés sin
    duplicar código.

---

## I. Distribución como `uv tool`

Objetivo: que un alumno instale y use todo con dos comandos, sin clonar el
repositorio ni instalar una toolchain:

```bash
uv tool install "hardboiled[zig]"     # o: uvx hardboiled ...
hardboiled run main.c                 # compila con el runtime incluido y abre la TUI
```

Estado verificado de la 1.0.0: `uv tool install` funciona y el comando queda
en el `PATH`, pero el wheel sólo contiene el código Python. Faltan `runtime/`,
`board.toml` y los ejemplos, y el compilador es una dependencia de desarrollo.

51. **Mover `runtime/` dentro del paquete** — 🔴 · S
    Pasar `crt0.s`, `hardboiled.ld` e `include/hardboiled.h` a
    `src/hardboiled/runtime/` y ubicarlos con `importlib.resources`. Es el
    requisito previo de todo lo demás: hoy el wheel no los trae.
52. **Extra opcional `hardboiled[zig]`** — 🔴 · S
    Pasar `ziglang` de `dev` a `[project.optional-dependencies]`. Queda en el
    mismo entorno aislado que la herramienta y se invoca con
    `sys.executable -m ziglang cc`. Sin el extra, la instalación sigue siendo
    liviana (el wheel de zig pesa decenas de MB) para quien ya tiene
    `riscv*-gcc`.
53. **`hardboiled build` con runtime y toolchain resueltos solos** — 🔴 · M
    Concreta la mejora 35 sobre la 51 y la 52: busca `riscv64-unknown-elf-gcc`
    o `riscv32-unknown-elf-gcc` y, si no hay, usa zig. Agrega flags, `-I`, `-T`
    y `crt0.s` por su cuenta (`hardboiled build main.c util.c -o main.elf`).
54. **`hardboiled run` acepta fuentes `.c`** — 🔴 · S
    Si recibe `.c`, compila en una caché y ejecuta. Se recompila sólo cuando
    cambian los fuentes (hash de contenido y flags). El ciclo editar-probar se
    reduce a un comando.
55. **Placa por defecto empaquetada** — 🟡 · S
    Incluir `board.toml` como recurso del paquete. `hardboiled validate` sin
    argumentos valida esa placa (hoy falla fuera del repo) y `hardboiled board
    init` copia una plantilla editable al directorio actual.
56. **Ejemplos empaquetados** — 🟡 · S
    `hardboiled examples` lista y copia `demo.c`, `mmio.c`, `traps.c`, etc.
    `hardboiled demo` compila y abre la demo interactiva: sirve de prueba de
    humo tras instalar.
57. **`hardboiled runtime`** — 🟡 · S
    Imprime las rutas del runtime (`--include`, `--linker-script`, `--crt0`)
    para Makefiles propios o para quien use gcc a mano:
    `-I$(hardboiled runtime --include)`.
58. **Integración con el editor** — 🟡 · S
    `hardboiled new` (mejora 36) genera también `compile_flags.txt` o
    `.clangd` con el target riscv32 y la ruta del header instalado. El
    autocompletado y los diagnósticos funcionan sin configurar nada.
59. **`hardboiled doctor`** — 🟡 · S
    Diagnóstico del entorno: versión de Python y Unicorn, compilador que se va
    a usar, runtime encontrado, soporte de colores y teclas de función de la
    terminal. Es lo primero que se pide en un foro de consultas.
60. **Configuración de usuario fuera del proyecto** — 🟢 · S
    `~/.config/hardboiled/config.toml` (o `%APPDATA%` en Windows) para
    atajos, tema, `clock_hz` y compilador preferido. Con el paquete instalado
    no hay "repositorio" donde guardar preferencias.
61. **Publicación en PyPI con Trusted Publishing** — 🔴 · M
    Workflow de GitHub Actions que publique al crear un tag y habilite
    `uvx hardboiled` y `uv tool upgrade hardboiled`. Antes, confirmar que el
    nombre `hardboiled` está libre en PyPI. Mientras tanto:
    `uv tool install git+https://…/hardboiled`.
62. **Test de empaquetado en CI** — 🟡 · S
    Construir el wheel, instalarlo con `uv tool install` en un directorio
    temporal (`UV_TOOL_DIR`) y correr `hardboiled demo --headless`. Así se
    detecta que falta un recurso, como pasa hoy con `runtime/`.
63. **Autocompletado de shell** — 🟢 · S
    `hardboiled completion bash|zsh|fish` para subcomandos, flags y archivos
    `.c`/`.elf`.

### Orden de implementación

Las dependencias entre mejoras fijan el orden:

1. **51 → 55 → 56**: con los recursos dentro del paquete, la herramienta
   instalada ya es autosuficiente.
2. **52 → 53 → 54**: compilación integrada; mayor ganancia de usabilidad.
3. **62 → 61**: se verifica el empaquetado en CI y recién después se publica.
4. **57, 58, 59, 60, 63**: mejoras independientes, en cualquier orden.

`tests/fixtures/build.py` y los tests que usan `ROOT / "board.toml"` deben
adaptarse cuando se haga la 51 y la 55.

---

## Prioridades sugeridas

Mayor impacto con menor esfuerzo, para una próxima versión:

| # | Mejora | Esfuerzo |
|---|---|---|
| 3 | Step Out | S |
| 10 | Pantalla post-mortem de la trampa | S |
| 24 | Generar `hardboiled.h` desde `board.toml` | S |
| 28 | Guardia de pila contra `.bss`/heap | S |
| 2 | Backtrace | M |
| 11 | Desensamblado mixto | M |
| 21 | UART RX | M |
| 35 | `hardboiled build` | M |
| 41 | Modo de prueba con salida esperada | M |
| 1 | Inspección de variables | L |
