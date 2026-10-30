# Sensores Android con Cyberdeck (ola 40)

Cyberdeck convierte el acelerómetro del teléfono en tres entradas analógicas del
emulador. Requiere Android 8+, una placa con ADC de al menos tres canales y una
red local compartida. El PIN es obligatorio incluso desde loopback.

## Preparar una práctica

Desde el repositorio de hardboiled:

```sh
uv sync --locked
uv run hardboiled run docs/examples/cyberdeck.c --board docs/examples/cyberdeck.toml --remote
```

La TUI comienza detenida en `main`: presioná continuar para leer los canales.
La TUI abre un panel con IP, puerto, PIN aleatorio de seis dígitos y QR.
Esc lo cierra y Ctrl+K lo vuelve a abrir. La terminal también imprime estos datos. Si la máquina
tiene varias interfaces, agregá `--remote-advertise-host 192.168.1.45` con su IP LAN.
`--remote-host` selecciona la interfaz de escucha (por defecto `0.0.0.0`) y
`--remote-port` el puerto (8767). `--remote` requiere la TUI.

Instalá el APK de `cyberdeck/app/build/outputs/apk/debug/app-debug.apk` y abrí
Cyberdeck. Elegí **Buscar en Wi-Fi** e ingresá el PIN, **Escanear QR**, o completá
IP/puerto/PIN manualmente. El QR contiene `bridge://pair?v=1.3&host=…&port=…&service=hardboiled&pin=…`.
El PIN se transmite en el handshake JSON; no queda en la URL WebSocket ni se guarda.
El escáner usa Google Code Scanner (ML Kit), que requiere Google Play Services.
La conexión manual y mDNS funcionan sin ese componente.

## Sensores y controles

- X/Y/Z corresponden a ADC 0/1/2 del primer ADC de la placa.
- −9,80665 m/s² → 0 mV; 0 → Vref/2; +9,80665 m/s² → Vref.
  Fuera de ese rango se satura; Vref se negocia con la placa.
- El selector permite 20–60 Hz. La app limita envíos con el timestamp del sensor.
- Sólo se muestran botones si la placa tiene pulsadores. El motor genera la
  pulsación y su liberación; el teléfono confirma con un pulso háptico de 15 ms.
- Si el primer periférico externo tiene IRQ, una sacudida >2,5g genera un pulso
  de 100 ms, con una espera de un segundo entre sacudidas. Al desconectarse,
  el puente baja esa línea.
- En una pérdida de red, la app detiene sensores y reintenta a 1/2/4/8/16/30 s,
  reutilizando un token efímero. Al salir de la app se apagan sensores y conexión.
  Al volver se requiere emparejar otra vez; las entradas conservan la última muestra.

## Contrato de red implementado

WebSocket `/ws`, envoltura JSON 1.3 de `cyberdeck/android-spec.md`:
`PAIR_REQUEST` → `PAIRING_SUCCESS` → `GET_CAPABILITIES` → `CAPABILITIES_LIST`.
El manifiesto declara `service=hardboiled`, ADC (`device`, `vref_mv`, canales,
frecuencias), botones e IRQ disponibles. Acciones:

```json
{"version":"1.3","action":"ADC_SAMPLE","payload":{"device":"adc0","millivolts":[0,1650,3300]}}
```

`BUTTON_PRESS` recibe `pin`; `IRQ_RAISE`/`IRQ_LOWER` reciben `device`.
Los comandos inválidos responden `INVALID_COMMAND` y no alteran el motor.
Se limita el tamaño a 4096 bytes, la cola pendiente a 256 y el emparejamiento a
15 segundos. Se rechazan orígenes web. Cinco PIN erróneos por IP bloquean un minuto.
PIN, comparación constante, tokens de ocho horas, QR y publicación mDNS reutilizan
`cast-tools-common` en su revisión fijada en el lockfile.

Se publica el tipo base `_bridge-remote._tcp.local.` con TXT `service=hardboiled`:
Android descubre ese tipo y filtra por TXT. No se depende del soporte de subtipos
DNS-SD de cada versión de Android. El QR es la alternativa si Wi-Fi bloquea multicast.
El transporte LAN de esta versión es `ws://`; usalo en la red del laboratorio.
UDP broadcast, TLS y servicio Android en segundo plano quedan fuera de esta ola.
