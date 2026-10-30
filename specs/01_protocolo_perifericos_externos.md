# Especificación del Protocolo de Periféricos Externos para Hardboiled

**Versión:** 1.0  
**Fecha:** 30/10/2026  
**Estado:** Aprobado / Implementado  
**Referencia:** Hoja de Ruta - Ola 33 (Paso 1) / Decisión G (29/10/26)

---

## 1. Propósito y Alcance

Esta especificación define la arquitectura, protocolo de comunicación y modelo temporal para conectar periféricos de hardware simulados como procesos externos independientes al emulador `hardboiled` (RV32I).

El objetivo es mantener el núcleo del emulador liviano y enfocado en los periféricos troncales pedagógicos (GPIO, ADC, UART, Timer, Display 7 segmentos), permitiendo que dispositivos más complejos o interactivos (teclados matriciales 4×4, displays LCD HD44780, controladores PWM multicanal con LED RGB, servos o aplicaciones Web/móviles) corran en procesos separados en cualquier lenguaje de programación sin recompilar ni alterar el binario principal de `hardboiled`.

---

## 2. Declaración en `board.toml`

Un periférico externo se declara en `board.toml` bajo la sección `[[peripherals]]` con el tipo `"external"`.

```toml
[[peripherals]]
name = "keypad"
type = "external"
offset = "0x50"
size = 16               # Tamaño de la ventana MMIO en bytes (múltiplo de 4)
irq_line = 3            # Línea de IRQ asociada (opcional, 0 a 7)
channel = "ipc"         # "ipc" (socket de streaming por defecto) o "script"
```

### Campos de configuración:
- `name` (string, obligatorio): Identificador único del periférico (ej. `"keypad"`, `"lcd"`, `"rgb_pwm"`).
- `type` (string, obligatorio): `"external"`.
- `offset` (hex/int, obligatorio): Dirección base relativa a `mmio_base` (0x40000000), alineada a 4 bytes.
- `size` (int, obligatorio): Cantidad de bytes mapeados en MMIO (mínimo 4, múltiplo de 4).
- `irq_line` (int, opcional): Número de línea en el PIC (0–7).
- `channel` (string, opcional): Modo de transporte (`"ipc"` para socket streaming o `"script"` para ejecución grabada en tests).

---

## 3. Modelo de Tiempo y Sincronización

La CPU de `hardboiled` simula un núcleo determinista ciclo a ciclo. La sincronización con los periféricos externos sigue las siguientes reglas normativas:

1. **El emulador es el dueño del tiempo (*Master Clock*):** El emulador transmite el avance de los ciclos de ejecución de la CPU (`cycle_sync`).
2. **Las lecturas MMIO no bloquean la CPU (*Non-blocking reads*):**
   - Para evitar cuelgues o latencias no deterministas en el lazo de ejecución del emulador, `hardboiled` mantiene un buffer local de registros sombra (*shadow registers*) del periférico externo.
   - Toda lectura MMIO (`read`) realizada por la CPU devuelve inmediatamente el valor del registro sombra correspondiente al offset pedido.
   - El proceso externo actualiza este estado de registros sombra mediante notificaciones asíncronas (`REG_UPDATE` / `IRQ_ASSERT`) o en puntos de sincronización de ciclo.
3. **Las escrituras MMIO se despachan de inmediato (*Write-through / buffered*):**
   - Cuando la CPU ejecuta una instrucción de escritura (`sw`, `sh`, `sb`), `hardboiled` actualiza su memoria local/sombra y despacha inmediatamente un mensaje `WRITE` con el offset relativo, el valor y la máscara de bits al proceso externo.
4. **Manejo de Interrupciones (IRQ):**
   - El proceso externo solicita activar o desactivar la línea de interrupción configurada enviando mensajes de control de línea IRQ.
   - La línea queda asertada en el PIC de `hardboiled` hasta que el proceso externo la desasierte o el firmware limpie la condición de interrupción en los registros MMIO del dispositivo.
5. **Modo Determinista en Pruebas (`hardboiled test`):**
   - En corridas de prueba automatizadas donde no se lanza un proceso cliente interactivo, los periféricos de tipo `external` aceptan ser estimulados mediante guiones TOML (`--script`), reproduciendo las escrituras de registros y disparos de IRQ en ciclos exactos sin jitter de red.

---

## 4. Protocolo de Mensajes (Framing y Payload)

La comunicación se realiza mediante un canal de flujo confiable (socket Unix en Linux/macOS o TCP loopback `127.0.0.1` en Windows/Linux, o WebSocket para frontends web).

Cada trama se envía como una línea de texto JSON delimitada por salto de línea (`\n` / Line-delimited JSON).

### 4.1. Mensajes Emulador → Proceso Externo (Servidor → Cliente)

| Comando | Parámetros | Descripción |
| :--- | :--- | :--- |
| `RESET` | `{"cycle": <int>}` | Señal de reset de hardware. El periférico debe volver a su estado de encendido. |
| `WRITE` | `{"reg": <int>, "val": <int>, "mask": <int>, "cycle": <int>}` | Escritura MMIO emitida por la CPU. `reg` es el offset relativo al periférico; `mask` indica los bytes/bits válidos. |
| `CYCLE` | `{"cycle": <int>}` | Avance del reloj del emulador emitido periódicamente o en eventos relevantes. |
| `QUIT` | `{}` | El emulador se cierra. El cliente debe finalizar limpiamente. |

### 4.2. Mensajes Proceso Externo → Emulador (Cliente → Servidor)

| Comando | Parámetros | Descripción |
| :--- | :--- | :--- |
| `REG_UPDATE` | `{"reg": <int>, "val": <int>}` | Actualiza el registro sombra del emulador en el offset relativo `reg`. |
| `IRQ_RAISE` | `{}` | Solicita levantar la línea de interrupción (`irq_line`) asignada en el PIC. |
| `IRQ_LOWER` | `{}` | Solicita bajar la línea de interrupción (`irq_line`) asignada en el PIC. |
| `PING` | `{"timestamp": <int>}` | Chequeo de latencia / keepalive. El emulador responde con `PONG`. |

---

## 5. Seguridad y Autenticación

Basado en la infraestructura transversal de `cast-tools-common`:

1. **Conexiones Locales:** Las conexiones originadas en `127.0.0.1` o sockets de dominio Unix pertenecen al mismo usuario local y no requieren PIN para desarrollo rápido en consola/TUI.
2. **Conexiones de Red / Navegador Web:**
   - Si la interfaz se expone hacia navegadores web o terminales remotas, se aplica el filtro de origen (`filtro_de_origen` / rechazo de cross-origin no autorizado).
   - Para conexiones móviles o remotas en el aula (ver especificación de Android), es obligatoria la autenticación por PIN efímero de 6 dígitos generado con entropía criptográfica (`secrets`) y limitación de tasa de intentos fallidos.
