# X360 Cloud Bridge

Usa tu **control inalámbrico de Xbox 360** (con su receptor USB) para jugar
**Xbox Cloud Gaming** y **GeForce NOW** en Chrome, en un Mac moderno, incluso con Apple Silicon.

No necesitas extensiones de kernel ni drivers, y no hay que tocar SIP, AMFI ni la NVRAM.

[Read in English](README.md)

## Cómo funciona

macOS nunca ha soportado el receptor inalámbrico de Xbox 360. Para que un control
aparezca a nivel de sistema hace falta un permiso restringido de Apple. Pero el juego
en la nube corre en el navegador, así que basta con que el control exista **dentro de la
página**:

```
Receptor 360 ──USB──▶ helper (Python + libusb) ──WebSocket 127.0.0.1:8360──▶ extensión de Chrome
                                                                                 │
                         navigator.getGamepads() en xbox.com / GeForce NOW ◀─────┘
```

## Instalación

```bash
brew install libusb
git clone https://github.com/Maverserker/x360-cloud-bridge.git
cd x360-cloud-bridge
./start.sh
```

Deja el helper corriendo mientras juegas. Para detenerlo, presiona `Ctrl+C`.

**Extensión** (una sola vez):

1. Abre `chrome://extensions`
2. Activa el **Modo de desarrollador**, arriba a la derecha
3. Haz clic en **Cargar descomprimida** y elige la carpeta `extension`

**Para jugar:** enciende el control con el botón Guide y abre [xbox.com/play](https://www.xbox.com/play)
o [play.geforcenow.com](https://play.geforcenow.com). Si la página ya estaba abierta, recárgala.

## Opciones

```bash
./start.sh --deadzone 0.2   # súbelo si los sticks se mueven solos (por defecto 0.15)
./start.sh --simulate       # control falso, sin receptor (para desarrollo)
```

## Problemas comunes

| Síntoma | Solución |
|---|---|
| El popup dice *Helper: not running* | Ejecuta `./start.sh` y deja la terminal abierta |
| *Receiver is in use by another program* | **Steam** acapara el receptor mientras está abierto. Ciérralo |
| El control no aparece en el juego | Recarga la pestaña del juego |
| El control no se empareja | Presiona el botón del receptor y luego el botón de conexión en la parte de arriba del control |

## Limitaciones

- Solo funciona en el navegador. **No** funciona con la app nativa de GeForce NOW, con
  juegos nativos de Mac ni con Steam.
- El helper tiene que estar corriendo mientras juegas.
- No hay soporte para el puerto de audífonos ni para el chatpad.

## Contribuir

Los issues y pull requests son bienvenidos. Con `./start.sh --simulate` y la página
`test/gamepad-test.html` puedes trabajar sin hardware. Los detalles están en el
[README en inglés](README.md#contributing).

## Licencia

[GPL-3.0-or-later](LICENSE). Puedes usar, estudiar, compartir y modificar este proyecto; si distribuyes una versión modificada, también debe publicarse bajo la GPL junto con su código fuente.
