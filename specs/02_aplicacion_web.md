# Especificación de la Aplicación Web de Periféricos Virtuales para Hardboiled

**Versión:** 1.0  
**Fecha:** 30/10/2026  
**Estado:** Implementado en ola 39 (02/11/26)
**Referencia:** Hoja de Ruta - Ola 33 (Paso 3) / Decisión G (29/10/26) / QoL #1220, #1223, #1227

---

## 1. Propósito y Arquitectura General

La aplicación web de periféricos de `hardboiled` ofrece un panel interactivo visual en el navegador web local que se conecta al emulador mediante WebSockets para simular y renderizar componentes de hardware interactivos de manera gráfica.

### Objetivos:
1. Renderizado interactivo de componentes que desbordan o enriquecen la interfaz TUI de terminal:
   - **Teclado matricial 4×4:** Keypad clickeable táctil/mouse con barrido de filas y lectura de columnas (QoL #1220).
   - **Display LCD alfanumérico 16×2:** Controlador tipo HD44780 con matriz de puntos 5×8, visualización del contraste, cursor parpadeante y memoria CGRAM/DDRAM (QoL #1227).
   - **LED RGB con PWM multicanal:** Visualización del ciclo de trabajo (*duty cycle*) de 0 a 100% y síntesis de color en tiempo real con canal alfa e integración visual (QoL #1223).
2. **Cero instalación para el estudiante:** Servido directamente por `hardboiled` en modo servidor local (`hardboiled run --web` o comando auxiliar).
3. **Conexión local confiable:** Basado en `cast-tools-common` sin necesidad de ingresar PIN para conexiones locales (`127.0.0.1` / `localhost`).

```
┌────────────────────────────────────────────────────────┐
│                   Navegador Web Local                  │
│  - Single Page Application (HTML5 / Vanilla JS / CSS3) │
│  - Render reactivo Canvas / SVG / DOM                  │
│  - WebSocket Client                                    │
└───────────────────────────▲────────────────────────────┘
                            │ ws://127.0.0.1:8767/ws
                            │ JSON Messages (Protocolo Externo)
┌───────────────────────────▼────────────────────────────┐
│                  hardboiled (Emulador)                 │
│  - Servidor HTTP embebido (estáticos SPA)              │
│  - WebSocket Server (bridge a bus MMIO / external)     │
│  - Núcleo RV32I + PIC + memoria                        │
└────────────────────────────────────────────────────────┘
```

---

## 2. Pantallas y Componentes Visuales

El panel web organiza los componentes en tarjetas desacopladas (*cards*) con estilo sobrio y técnico:

### 2.1. Panel del Teclado Matricial 4×4
- **Disposición:** Matriz 4 filas × 4 columnas con teclas `[1, 2, 3, A]`, `[4, 5, 6, B]`, `[7, 8, 9, C]`, `[*, 0, #, D]`.
- **Interacción:** Click con el mouse o mapeo directo al teclado físico de la computadora (teclado numérico `NumPad` y teclas `A-D`).
- **Estado de barrido:** Indicadores luminosos laterales que muestran qué fila está actualmente energizada en nivel bajo/alto por el firmware del microcontrolador y qué columnas cierran circuito.

### 2.2. Panel del Display LCD 16×2 (HD44780)
- **Aspecto visual:** Pantalla retroiluminada color verde clásico / azul con matriz de dos filas de 16 caracteres.
- **Microoperaciones:** Decodificación visual de comandos:
  - Limpieza de pantalla (`Clear Display`).
  - Retorno al inicio (`Return Home`).
  - Modo de entrada (`Entry Mode Set`: incremento/decremento).
  - Encendido/apagado de display, cursor y parpadeo (*Blink*).
  - Desplazamiento de texto (*Shift*).
- **Inspección de diagnóstico:** Panel lateral colapsable con el contenido hexadecimal de la memoria DDRAM (direcciones 0x00–0x0F y 0x40–0x4F) y CGRAM (caracteres personalizados).

### 2.3. Panel de Salida PWM y LED RGB
- **Visualizador de Canales:** Barras gráficas de nivel porcentual (0% a 100%) para los canales Rojo (R), Verde (G) y Azul (B).
- **LED RGB simulado:** Círculo emisor de luz difusa que computa la mezcla cromática RGB en CSS (`rgb(R, G, B)`) combinando el ciclo de trabajo de cada señal cuadrada.
- **Frecuencia y ciclo de trabajo:** Muestra numérica en tiempo real de la frecuencia calculada en Hz y del período en microsegundos.

---

## 3. Protocolo de Comunicación Web y Flujo de Mensajes

La aplicación web se conecta a través del protocolo estandarizado en `01_protocolo_perifericos_externos.md`, transportado sobre WebSocket en formato JSON:

### 3.1. Handshake de Conexión
1. La SPA web abre `ws://127.0.0.1:8767/ws`.
2. El emulador verifica que el origen provenga de loopback (`conexion_local_confiable`).
3. El emulador transmite el mensaje de bienvenida con el catálogo de periféricos externos activos:
   ```json
   {
     "type": "HELLO",
     "board": "lab-rv32-basics",
     "peripherals": [
       {"name": "keypad", "type": "keypad_4x4", "offset": 80, "size": 16},
       {"name": "lcd", "type": "lcd_hd44780", "offset": 96, "size": 16},
       {"name": "rgb_pwm", "type": "pwm_rgb", "offset": 112, "size": 16}
     ]
   }
   ```

### 3.2. Intercambio de Eventos
- **Pulsación de tecla en teclado matricial:**
  El usuario hace click en la tecla `'5'` (Fila 1, Columna 1). El frontend envía:
  ```json
  {"cmd": "KEY_EVENT", "device": "keypad", "row": 1, "col": 1, "pressed": true}
  ```
  El emulador computa el cambio sobre el registro sombra de columnas y dispara la IRQ si el firmware tiene habilitada la interrupción por cambio de pines.

- **Escritura del firmware en el LCD:**
  El microcontrolador escribe un carácter `'H'` (0x48) en el registro de datos:
  ```json
  {"type": "WRITE", "device": "lcd", "reg": 4, "val": 72, "mask": 255, "cycle": 145020}
  ```
  La SPA procesa la instrucción, actualiza el cursor y redibuja la matriz visual en el Canvas HTML5.

---

## 4. Política de Seguridad y Despliegue Local

- **Acceso sin PIN:** Al correr exclusivamente sobre el loopback local del estudiante, no se solicita PIN para maximizar la ergonomía y velocidad de uso en clase.
- **Protección de Origen:** El backend rechaza peticiones cuyo header `Origin` no coincida con el puerto local servido, previniendo secuestros por sitios web externos maliciosos abiertos en otra pestaña del navegador.


## 5. Contrato implementado en ola 39

La [guía operativa](../docs/panel_web.md) detalla el mapa MMIO, la placa y el
firmware reproducible. `hardboiled run --web` sirve la SPA en **8768** por defecto
para coexistir con el puente móvil (8767); `--web-port` permite cambiarlo.
Los bloques `type="external"` declaran `external_model` explícito.

El estado de keypad, LCD y PWM reside en modelos del emulador. La SPA recibe
`HELLO` y snapshots `STATE` por WebSocket (hasta 30 Hz), en vez de interpretar
cada `WRITE` en el navegador. Las escrituras MMIO se procesan inmediatamente por
el modelo, y todas las entradas y consultas pasan por la cola del runner. Esto
permite recarga, reconexión y paso atrás sin perder DDRAM/CGRAM ni mantener logs
ilimitados de barrido. Las filas del teclado son activas en **alto**, en
compatibilidad con `Keypad4x4` y el ejemplo de ola 33.

El servidor sólo escucha en loopback, valida Host y Origin del propio puerto,
no requiere PIN y aplica CSP. La TUI muestra la URL y la abre con Ctrl+W. El LCD
usa un adaptador MMIO de bytes completos (busy=0), con glifos CGRAM 5x8 y una ROM
visual latina simplificada. La práctica y las pruebas fijan este contrato.
