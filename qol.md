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

---

## J. Más hardware virtual y sensores

Todos los periféricos actuales heredan de `Peripheral`: registros MMIO con
`read`/`write`, tiempo con `next_deadline`/`service` y despertar de `wfi` con
`can_wake`. Las propuestas de esta sección entran en ese mismo molde. Cada una
necesita además un widget en la vista de hardware y una forma de estimularla
desde la TUI, el guion de entrada (#44) y `HardwareLoop` en los tests.

Los sensores son entradas que el alumno puede mover (slider, tecla o guion) o
que siguen un modelo físico sencillo con ruido opcional. Así la lectura cambia
sola y el programa tiene que filtrarla, promediarla o reaccionar.

### Sensores

64. **ADC multicanal con potenciómetros** — 🔴 · M
    Convertidor de 10/12 bits y 4 u 8 canales: se elige un canal, se pide la
    conversión, se espera `DONE` (por sondeo o IRQ) y se lee el resultado. La
    conversión tarda una cantidad de ciclos configurable. En la TUI, cada
    canal se conecta a un potenciómetro que se gira con el mouse o las
    flechas. Es la base de los sensores analógicos que siguen.
65. **Sensor de temperatura analógico (tipo LM35)** — 🟡 · S
    Un canal del ADC entrega 10 mV/°C. La temperatura se fija en la TUI o
    sigue una curva (rampa, senoide diaria) con ruido gaussiano. Sirve para
    practicar la conversión a unidades, los enteros de punto fijo y el
    promedio móvil.
66. **Sensor de luz (LDR) con perfil ambiente** — 🟢 · S
    Divisor resistivo no lineal sobre el ADC y un perfil día/noche o
    "linterna" controlable. Buen ejercicio de histéresis: encender una luz
    cuando oscurece sin que parpadee en el umbral.
67. **Sensor ultrasónico de distancia (tipo HC-SR04)** — 🟡 · M
    El firmware da un pulso en `TRIG` y mide cuánto dura `ECHO`, que es
    proporcional a la distancia (58 µs/cm con el `clock_hz` de la placa). La
    distancia se ajusta en la TUI. Enseña a medir tiempos con el timer y a
    poner un timeout cuando no hay eco.
68. **Sensor de temperatura y humedad por un cable (tipo DHT22)** — 🟢 · M
    Protocolo de un solo cable con tiempos estrictos: el firmware saca el
    pulso de inicio, el sensor contesta 40 bits por ancho de pulso y el último
    byte es un checksum. Si se lee a destiempo, el checksum falla, como en la
    placa real. Necesita la #69.
69. **GPIO bidireccional con pull-ups e IRQ por pin** — 🔴 · M
    Puerto de 8 o 16 pines con registros `DIR`, `OUT`, `IN`, `PULL` e IRQ por
    flanco en cada pin. Detecta el cortocircuito cuando dos salidas pelean
    por la misma línea. Es la base del bit-banging (#68, #71) y reemplaza el
    par fijo de LEDs y switches en placas personalizadas.
70. **Controlador I2C con una IMU virtual (tipo MPU-6050)** — 🔴 · L
    Un controlador I2C maestro (START, dirección, ACK/NACK, lectura y
    escritura de registros, STOP) al que se enchufan esclavos definidos en
    `board.toml`. El primero sería una IMU con `WHO_AM_I`, acelerómetro y
    giroscopio, y la orientación se cambia en la TUI inclinando un "nivel de
    burbuja". Un NACK por una dirección equivocada se explica con una pista
    (#30). Otros esclavos posibles: el RTC (#80) y un expansor de E/S.
71. **Controlador SPI con EEPROM/flash externa persistente** — 🟡 · M
    Una SPI maestra (modo 0, `CS` por GPIO) y una memoria serie con comandos
    `READ`, `WRITE`, `WREN` y `RDSR`, más su tiempo de escritura. El contenido
    se guarda en un archivo junto al ELF, así que los datos sobreviven al
    Reset y entre sesiones. Ejercicios típicos: un contador de arranques, un
    registro de datos y el desgaste por escrituras.

### Entradas humanas

72. **Teclado matricial 4×4** — 🔴 · M
    El firmware activa una fila por vez y lee las columnas. En la TUI se
    dibuja un keypad clickeable que también responde al teclado numérico.
    Enseña el barrido, la detección de varias teclas a la vez y el armado de
    un PIN o una calculadora.
73. **Encoder rotativo en cuadratura con pulsador** — 🟡 · S
    Las señales A/B desfasadas generan una IRQ por flanco y la TUI permite
    girar el encoder con la rueda del mouse. Ejercicios: decodificar el
    sentido, contar pasos perdidos si la ISR es lenta y navegar menús.
74. **Rebote de contactos configurable** — 🔴 · S
    Opción `bounce_cycles` en botones y switches: al cambiar de estado, la
    señal oscila unos microsegundos antes de estabilizarse. Aparece así el
    bug clásico de "apreté una vez y contó tres", y el antirrebote por
    software deja de ser teoría. No es un periférico nuevo, pero hace
    realistas a todos los de entrada.

### Actuadores y salidas

75. **PWM multicanal y LED RGB** — 🔴 · M
    Canales con período y ciclo de trabajo propios. La TUI muestra el ciclo de
    trabajo como brillo y, sobre un LED RGB, mezcla el color (con truecolor, o
    con un bloque y el valor numérico si la terminal no lo tiene). Es la base
    de los actuadores #76 y #78.
76. **Servo y motor DC con puente H y encoder** — 🟡 · M
    El servo lee pulsos de 1 a 2 ms a 50 Hz y la TUI dibuja la aguja en su
    ángulo. El motor DC usa `IN1`/`IN2` y PWM, tiene inercia de primer orden y
    un encoder que devuelve las RPM. Así se puede cerrar un lazo de velocidad
    (P/PI). Detecta el cortocircuito del puente (`IN1 = IN2 = 1` con PWM).
77. **Motor paso a paso** — 🟢 · S
    Cuatro bobinas en paso completo o medio paso, con la posición angular
    dibujada en la TUI. Si la secuencia es inválida o los pasos son demasiado
    rápidos, el motor "pierde pasos" y se avisa del motivo.
78. **Buzzer / generador de tonos** — 🟢 · S
    Una frecuencia derivada del PWM o de un registro `FREQ`. La TUI muestra la
    nota más cercana (la4 = 440 Hz). Opcionalmente suena de verdad con la
    campana de la terminal o un backend de audio opcional. Permite tocar una
    melodía con el timer.
79. **Display LCD 16×2 (controlador HD44780)** — 🔴 · M
    Interfaz paralela de 4 u 8 bits con `RS`/`E`, el juego de comandos real
    (clear, posición del cursor, caracteres propios en CGRAM) y los tiempos
    de ejecución de cada comando. La TUI dibuja el panel verde con sus dos
    líneas. Mandar un comando antes de que termine el anterior se señala como
    error, que es un tropiezo clásico al portar a hardware real.
80. **Reloj de tiempo real (RTC) con alarma** — 🟡 · S
    Fecha y hora en BCD que avanzan con los ciclos de la CPU, así que respetan
    `clock_hz` y la cámara lenta (#26), más una alarma que pide IRQ. Puede
    arrancar con la hora del sistema. Útil para relojes, registros con fecha
    y el modo de bajo consumo combinado con `wfi`.
81. **Matriz de LEDs 8×8 multiplexada** — 🟡 · M
    Se enciende una fila por vez y la TUI integra el brillo según el tiempo
    que cada LED estuvo prendido (persistencia de la visión). Si el barrido es
    lento, la imagen parpadea o se ve tenue, lo que ilustra la relación entre
    la frecuencia de refresco y el reloj.

### Sistema

82. **Watchdog** — 🟡 · S
    Si el firmware no lo alimenta a tiempo (`KICK` con una clave), la placa se
    reinicia. Al reiniciar, el depurador se detiene y explica: "el watchdog
    reinició la placa: el último kick fue en main.c:42 hace N ciclos". Un
    registro `RESET_CAUSE` distingue el encendido del reinicio por watchdog.
    Es un tema clave de firmware robusto.
83. **Planta física simulada para control en lazo cerrado** — 🔴 · L
    Modelos que unen sensores y actuadores de esta sección: un horno
    (resistencia por PWM → temperatura con retardo), un tanque (bomba →
    nivel), un péndulo o un motor con carga. Se describen en `board.toml`
    (parámetros, ruido, perturbaciones programadas) y la TUI grafica la
    consigna y la salida en el tiempo. Es el hardware-in-the-loop completo
    para prácticas de control (on/off con histéresis, PID) y se evalúa con
    `HardwareLoop` o el modo de prueba (#41): "llega a 80 °C en menos de 5 s
    sin pasarse más de 2 °C".

### Consideraciones de diseño

- **Líneas de IRQ**: el PIC tiene 8 y ya se usan 3. ADC, GPIO, I2C, SPI,
  encoder, RTC y watchdog no entran todos, así que hay que llevar el PIC a 16
  o 32 líneas. Eso cambia `IRQ_LINES`, la tabla de vectores de `crt0.s` y el
  SDK generado (#24).
- **Mapa MMIO**: la ventana de 4 KB alcanza de sobra si cada periférico se
  alinea a 16 o 32 bytes. Conviene que `hardboiled board` sugiera offsets
  libres al agregar uno.
- **Tiempo**: los protocolos con tiempos estrictos (#67, #68, #79) dependen de
  que ciclos = tiempo (`clock_hz`). Hay que documentar que el tiempo es
  simulado y no depende de la velocidad del host.
- **Placas de ejemplo**: en lugar de sumar todo a la placa por defecto,
  ofrecer placas temáticas empaquetadas (`hardboiled board init --preset
  sensores|motores|control`), cada una con su ejemplo en C.
- **Estímulos reproducibles**: cada entrada nueva (potenciómetro, distancia,
  keypad, encoder) debe poder manejarse desde el guion de entrada (#44), para
  que la corrección automática no dependa de la TUI.

### Orden sugerido

1. **69 → 74 → 64**: la base de la que dependen casi todos los demás (GPIO
   genérico, entradas realistas, ADC).
2. **65, 72, 75, 79**: los de mayor valor en el aula con esfuerzo acotado.
3. **70, 71, 67, 68**: buses y protocolos con tiempos estrictos.
4. **76, 81, 82, 80, 73, 77, 78, 66**: actuadores y sistema.
5. **83**: la planta simulada, que integra todo lo anterior.
