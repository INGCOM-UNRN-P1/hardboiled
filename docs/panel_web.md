# Panel web de periféricos (ola 39)

El panel se sirve desde `hardboiled`, sin Node, npm, CDN ni servicios externos.
Abre una SPA local con teclado matricial, LCD de puntos 16x2 y LED RGB con PWM.
El estado MMIO reside en el motor: cerrar el navegador no detiene el firmware y
recargar la página recupera sus salidas actuales.

## Probar una práctica

Desde el repositorio:

```sh
uv sync --locked
uv run hardboiled run docs/examples/panel_web.c --board docs/examples/panel_web.toml --web
```

La TUI muestra la URL en el encabezado; **Ctrl+W** abre el navegador. También podés
abrir `http://127.0.0.1:8768/` a mano. El programa se detiene al inicio de `main`:
continuá con **F5** para ver el saludo y los tres niveles PWM. Mantené una tecla
con el mouse, tocala en pantalla o usá 0–9, A–D, `*` y `#`. El firmware recorre
las filas, lee las columnas, muestra la tecla en el LCD y enciende el canal rojo
al 100%. Al soltarla vuelve a 25% (verde 50%, azul 75%).

`--web-port N` elige otro puerto; `--web-port 0` asigna uno libre y muestra la URL
real. El puerto por defecto es **8768**, separado del puente móvil de ola 40
(8767), por lo que `--web` y `--remote` pueden coexistir en una placa con ADC.
`--web` requiere la TUI y al menos un periférico con `external_model`.

## Declarar los periféricos

Cada modelo usa una ventana MMIO de 16 bytes. El nombre es libre y se muestra en
el panel; `external_model` determina su comportamiento, sin inferirlo del nombre.

```toml
[[peripherals]]
name = "keypad"
type = "external"
offset = "0x50"
external_size = 16
external_model = "keypad_4x4"
irq_line = 3
```

Para el LCD usá `external_model = "lcd_hd44780"` y para el LED
`external_model = "pwm_rgb"`, cada uno en su ventana sin superposiciones.
La [placa completa](examples/panel_web.toml) y el [firmware](examples/panel_web.c)
son una práctica compilable con el SDK existente. El firmware usa direcciones
explícitas para mostrar qué registros modifica.

| Modelo | +0x00 | +0x04 | +0x08 | +0x0c |
| --- | --- | --- | --- | --- |
| keypad_4x4 | Filas activas en alto (bits 0–3) | Columnas, calculadas por contacto | CTRL: bit 0 habilita IRQ | Reservado |
| lcd_hd44780 | Comando (byte bajo) | Dato (byte bajo) | Dirección actual, busy=0 | Reservado |
| pwm_rgb | Período en ticks de CPU | Compare rojo | Compare verde | Compare azul |

El teclado sigue la convención en alto del modelo `Keypad4x4` de ola 33. Un
contacto en una fila activa levanta su columna; al soltar baja. Con CTRL bit 0 y
`irq_line` configurados, una columna activa mantiene esa IRQ hasta que cese la
condición. La tecla es una entrada física: ninguna lectura bloquea la CPU.
Las distintas pestañas mantienen sus pulsaciones por separado; cerrar una libera
sólo sus teclas. El cliente libera las propias al perder foco o visibilidad.

El LCD soporta limpiar, volver al inicio, selección de DDRAM/CGRAM, incremento o
decremento, desplazamiento, display/cursor/blink y ocho glifos personalizados de
5x8. La memoria tiene dos filas de 40 caracteres; se muestran 16 por fila. El
inspector enseña DDRAM y CGRAM en hexadecimal; el contraste sólo afecta la vista.
La ROM visual representa letras latinas, números y puntuación habitual; los códigos
no dibujados aparecen como `?`, conservando su valor en memoria. Es un adaptador
MMIO de bytes completos: no emula los pines RS/E ni los tiempos busy del chip físico.

El RGB muestra `min(compare / período, 1)` por canal y se apaga si el período es
cero. La frecuencia es `clock_hz / período` y el período en microsegundos es
`período * 1e6 / clock_hz`. Sin reloj nominal, se muestran ticks sin inventar Hz.

Los modelos participan de reset y de snapshots: el paso atrás restaura DDRAM,
CGRAM, barrido y PWM. Los periféricos `external` sin modelo conservan el protocolo
de registros sombra de ola 33 y el uso con guiones.

## Transporte y seguridad

Sólo se escucha en **127.0.0.1**. No se requiere PIN: HTTP comprueba el `Host` y
WebSocket exige el `Origin` exacto de la página servida (IP o localhost, mismo
puerto). Se rechazan sitios externos, `Origin: null`, WS sin Origin, hosts ajenos
y rutas fuera de los tres recursos empaquetados. No se habilita CORS. La política
CSP permite únicamente código, estilos y conexiones del propio origen.

La conexión es `ws://127.0.0.1:8768/ws`, JSON por mensaje:

- `HELLO`: nombre de placa y catálogo `{name,type,offset,size}`.
- `KEY_EVENT`: `{cmd:"KEY_EVENT",device:"keypad",row:1,col:1,pressed:true}`.
- `STATE`: `{type:"STATE",cycle,clock_hz,devices:{…}}`, hasta 30 veces/s.
- `ERROR`: evento inválido, sin modificar el motor.

El navegador envía entradas por la cola del runner. Un `CmdWebState` obtiene una
copia completa en ese mismo hilo; la red nunca lee ni escribe la CPU en paralelo.
Las escrituras de firmware se procesan inmediatamente por el modelo. La SPA
recibe snapshots, en lugar de reproducir un log de cada `WRITE`: así conserva
los efectos intermedios y recupera todo el estado después de una desconexión sin
crecer con el número de instrucciones. El motor es la única fuente del tiempo.

Se admiten hasta ocho paneles, mensajes de 1024 bytes y hasta 128 comandos web
pendientes (las liberaciones al desconectarse tienen prioridad). Los clientes
lentos se desconectan; no bloquean la CPU. La SPA reintenta con espera de 1 a 10 s.

## Verificar

```sh
uv run pytest tests/test_panel_models.py tests/test_web.py tests/test_packaging.py -q
uv sync --locked --group browser
uv run --group browser playwright install chromium
HARDBOILED_BROWSER=1 uv run --group browser python -m pytest tests/test_web_browser.py -q
```

El CI tiene un job Linux con Chromium y el firmware real: pulsación y liberación,
lectura MMIO, texto LCD, PWM, pérdida de foco, recarga y ancho móvil de 375 px.
Las pruebas de protocolo también cubren origen, Host, recursos estáticos, mensajes
inválidos, múltiples pestañas y liberación al desconectarse. Los archivos HTML,
CSS y JS se verifican dentro del wheel.
