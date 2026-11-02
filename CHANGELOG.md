# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
versiones según [SemVer](https://semver.org/lang/es/).


## [Sin publicar]

### Agregado

- Ola 39: `run --web` y `--web-port`, SPA local empaquetada de teclado 4x4, LCD
  HD44780 16x2 (DDRAM/CGRAM) y LED RGB con PWM. Modelos MMIO con snapshots,
  entradas por cola y sincronización WebSocket; apertura desde la TUI con Ctrl+W,
  control de Host/Origin, práctica en C y CI de navegador con firmware real.

- Ola 42: en la vista de la pila, cada puntero local dice a qué apunta: otra variable de
  la pila (`p → v[2]`), una global (`f → triangulo`), una función o `NULL`.
- Ola 40: puente `run --remote` para Cyberdeck, PIN obligatorio, tokens efímeros,
  mDNS y QR compartidos con cast-tools-common. Muestras de tres ejes al ADC por
  cola del motor, pulsadores y pulso de IRQ externo; guía y práctica reproducible.

- `hardboiled_test.h`: aserciones para probar firmware desde C sobre los registros de E/S (`HB_ASSERT_REG_EQ`, bits y campos, pull-ups, IRQ habilitadas y pendientes, `HB_ASSERT_CYCLES_AT_MOST`, `HB_ESPERAR`), con el resultado por la UART y el código de salida. Ejemplo `pruebas.c` (Ola 21).
- Contador de ciclos determinista en el PIC (`HB_CYCLES_LO`/`HB_CYCLES_HI`, `hb_cycles()`): `rdcycle` en el emulador devuelve tiempo del equipo y cambia entre corridas.
- `hardboiled test`: `[[case.check]]` (LEDs, display, pines del GPIO y UART en un ciclo dado) y `until_cycle`/`until_ms` para firmware que no termina; `--press BOTÓN@MOMENTO` y `--hasta MOMENTO` sin TOML.
- TUI: los botones se aprietan con `Alt+0`–`Alt+7` (antes sólo con el mouse); reasignables como `button_N`.

### Corregido

- Con una placa propia, el SDK generado en la caché no incluía los headers fijos del runtime.

## [1.1.0] - 2026-09-28

Primera versión con registro de cambios; lo anterior está en el historial de git.

### Agregado

- **cli**: cumplir el contrato de línea de comandos de LINEAMIENTOS §3.2 (N-ECO-04) (`b7083e7`)

### Documentación

- **manual**: enlace relativo al header del runtime (N-ECO-17) (`8456b80`)
- **instalacion**: instalar hardboiled desde el repositorio y no por nombre (N-HARDBOILED-01) (`2920dea`)
- incorporar manual de uso integral y referencia tecnica (hardboiled) (`e47d576`)

### Mantenimiento

- **calidad**: verificar errores de Python y dependencias vulnerables (N-ECO-08, N-ECO-13) (`abf02e8`)
