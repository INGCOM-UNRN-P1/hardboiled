# Especificación de la Aplicación Android de Periféricos y Sensores para Hardboiled

**Versión:** 1.0  
**Fecha:** 30/10/2026  
**Estado:** Implementado en ola 40 (módulo Android y puente remoto)
**Referencia:** Hoja de Ruta - Ola 33 (Paso 4) / Decisión G (29/10/26)

---

## 1. Decisión de Arquitectura: Módulo de Cyberdeck vs. App Propia

### Decisión Adoptada: Módulo de Cyberdeck
Se resuelve integrar el soporte de periféricos remotos y sensores de `hardboiled` como un **módulo dedicado dentro de la aplicación Android `cyberdeck`**, en lugar de crear una aplicación móvil independiente y fragmentada.

### Justificación Técnica y Operativa:
1. **Infraestructura Unificada de Red y Descubrimiento:** `cyberdeck` ya implementa el stack completo de descubrimiento mDNS/DNS-SD (`_bridge-remote._tcp.local.`), fallback UDP Broadcast (puerto 8760), escaneo de códigos QR con CameraX + ML Kit y reconexión exponencial sobre WebSockets con OkHttp/Ktor.
2. **Seguridad y Criterio de Cátedra:** Reutiliza de forma directa el esquema de autenticación por PIN efímero de 6 dígitos y limitación de tasa de intentos fallidos estandarizado en `cast-tools-common`.
3. **Mantenibilidad y Distribución en el Aula:** Los estudiantes y docentes mantienen instalada una única aplicación APK en sus dispositivos móviles Android para interactuar con todas las herramientas de aula del ecosistema (`meet-tools`, `slide-tools` y el laboratorio bare-metal de `hardboiled`).
4. **Arquitectura Orientada a Capacidades (*Capability-Driven UI*):** La arquitectura de `cyberdeck` (ver especificación de Android en `cyberdeck/android-spec.md`) negocia dinámicamente un manifiesto de capacidades al conectar. Cuando se conecta a una sesión de `hardboiled`, activa la vista de hardware virtual.

---

## 2. Flujo de Emparejamiento en el Aula

Para vincular el teléfono del estudiante con la instancia de `hardboiled` que corre en su laptop o PC de laboratorio:

```
┌─────────────────────────┐                 ┌──────────────────────────┐
│  Estudiante / Teléfono  │                 │    Laptop / hardboiled   │
│       (cyberdeck)       │                 │      (Bridge Server)     │
└────────────┬────────────┘                 └────────────┬─────────────┘
             │                                           │
             │        1. Inicia emulador con --remote    │
             │ ────────────────────────────────────────> │ Genera PIN efímero (6 dígitos)
             │                                           │ Muestra QR en terminal (ASCII)
             │                                           │ Publica mDNS (_hardboiled-bridge)
             │                                           │
             │ 2. Escaneo de QR o Detección mDNS         │
             │    (Lee ws://192.168.1.45:8767?pin=123456)│
             │ ────────────────────────────────────────> │
             │                                           │
             │ 3. Handshake WebSocket + Auth PIN         │
             │ ────────────────────────────────────────> │ Valida PIN constante en tiempo
             │ <──────────────────────────────────────── │ Emite Token Efímero de sesión
             │                                           │
             │ 4. Transmisión de Capacidades y Sensores  │
             │ <=======================================> │ Streaming bidireccional
```

1. **Descubrimiento Automático:** La app móvil detecta el servicio en la red Wi-Fi del aula vía mDNS (`_hardboiled-bridge._sub._bridge-remote._tcp.local.`).
2. **Emparejamiento Rápido con QR:** Si la red del aula bloquea multicast/mDNS, el estudiante presiona "Escanear QR" en `cyberdeck` y apunta a la terminal donde `hardboiled` imprime el código QR ASCII (generado con `cast-tools-common.discovery.generate_qr_ascii`).
3. **Autenticación con PIN:** Si se conecta por IP manual, la app solicita ingresar el PIN de 6 dígitos desplegado en el banner de la sesión.

---

## 3. Mapeo de Sensores y Controles Táctiles del Teléfono

La aplicación móvil expone los componentes de hardware del smartphone como periféricos virtuales mapeados en el espacio MMIO del emulador:

### 3.1. Acelerómetro como Canales ADC (Ejes X, Y, Z)
- **Sensor:** Acelerómetro de 3 ejes del dispositivo (`Sensor.TYPE_ACCELEROMETER`).
- **Mapeo a ADC:** Las aceleraciones gravitacionales se normalizan al rango de tensión del ADC de `hardboiled` (0 a 3300 mV, referencia `vref_mv`):
  - Canal ADC 0: Eje X (Inclinación lateral).
  - Canal ADC 1: Eje Y (Inclinación longitudinal).
  - Canal ADC 2: Eje Z (Fuerza normal).
- **Frecuencia de Muestreo:** Configurable entre 20 Hz y 60 Hz para equilibrar consumo de batería y suavidad de control en prácticas de control/robótica simulada.

### 3.2. Botones Táctiles de Entrada y Pantalla Háptica
- **Pulsadores virtuales:** Banco de botones táctiles personalizables que emulan los pulsadores de hardware (`ButtonBank` / `buttons`).
- **Confirmación háptica:** Uso del subsistema de vibración (`Vibrator` / `VibratorManager`) con pulsos cortos (< 20 ms) al presionar cada botón para dar retroalimentación física al estudiante.

### 3.3. Simulación de Interrupciones Externas
- Al agitar el teléfono bruscamente (detección de sacudida / *shake gesture* por umbral de aceleración > 2.5g), la app emite un evento `IRQ_RAISE` hacia la línea de interrupción externa asignada, simulando una alarma de impacto o vibración en sistemas embebidos automotrices/industriales.

---

## 4. Requisitos de Plataforma Móvil

- **Sistema Operativo:** Android 8.0+ (API nivel 26 o superior).
- **Framework UI:** Jetpack Compose con componentes Material 3.
- **Red:** Cliente WebSocket sobre OkHttp con soporte para TLS local opcional y reconexión automática transparente en caso de suspensión de pantalla.
- **Permisos de Android:**
  - `android.permission.INTERNET` y `ACCESS_NETWORK_STATE`: Comunicación socket en red local.
  - `android.permission.CAMERA`: Escaneo del QR de emparejamiento.
  - `android.permission.VIBRATE`: Retroalimentación háptica en botones táctiles.
  - `android.permission.HIGH_SAMPLING_RATE_SENSORS`: Lectura fluida de acelerómetro.

## 5. Implementación de ola 40

Ver [guía operativa y contrato efectivo](../docs/cyberdeck.md) y
[cliente Cyberdeck](../../cyberdeck/README.md). Se usa el QR `bridge://pair` y
el tipo mDNS base con TXT `service=hardboiled`, compartidos con las otras
herramientas. El escáner usa Google Code Scanner (ML Kit), sin permiso de cámara.
La app negocia Vref, mapea −g…+g al rango ADC y transmite a 20–60 Hz sólo en
primer plano. El puente aplica comandos en la cola del motor. La API de placa
usa `external_size` para periféricos externos. UDP, TLS opcional y servicio en
segundo plano no son requisitos de cierre de esta ola.
