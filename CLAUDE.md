# CLAUDE.md — theia-player

Fork de [theia-player](https://github.com/Gheat1/theia-player). TUI music player para Navidrome/Subsonic, escrito en Python con Textual + libmpv.

**Repo:** `github.com/rodmera/theia-player`
**Upstream:** `github.com/Gheat1/theia-player` (remote `upstream`) — hacer `git fetch upstream` para traer cambios futuros

## Requisitos del Sistema (OS Dependencies)

A diferencia de `theia-subtui` (que invoca al reproductor CLI estándar por subproceso), `theia-player` utiliza bindings de C en Python (`python-mpv`) que requieren obligatoriamente de la **biblioteca dinámica compartida** en memoria (`libmpv.so`). Asegúrate de instalar la biblioteca de C del sistema operativo para que la reproducción funcione de forma asíncrona:

*   **Ubuntu / Debian:** `sudo apt install libmpv2`
*   **Arch Linux:** `sudo pacman -S mpv` (provee la librería compartida nativamente)
*   **macOS (Homebrew):** `brew install mpv`
*   **Windows:** Descargar y colocar `libmpv-2.dll` dentro del PATH.

## Reglas de código

- **`python3` siempre**, nunca `python`
- **Leer antes de editar** — el código upstream es limpio; no romper patrones existentes
- **Sin features no pedidas** — bug fix = bug fix
- **Sin Co-Authored-By ni atribución a IA** en commits

## Arquitectura

```
theiaplayer/app.py         layout, workers, playback glue, keybindings
theiaplayer/api.py         cliente async Subsonic (httpx), token auth, cache de covers
theiaplayer/player.py      wrapper libmpv + NullPlayer fallback si mpv no está
theiaplayer/playqueue.py   lógica de cola/shuffle/repeat — sin UI, puro lógica
theiaplayer/config.py      carga player.toml; build_bindings() genera BINDINGS desde config
theiaplayer/mpris.py       MPRIS2 D-Bus bidireccional (dbus-python); GLib loop en hilo daemon
theiaplayer/discord_rpc.py Discord Rich Presence via pypresence; no-op si no está instalado
theiaplayer/anim.py        primitivas de animación: shimmer, smooth_bar, marquee, viz
theiaplayer/widgets.py     Logo, Visualizer, NowPlaying (transport animado)
theiaplayer/nowplaying_mac.py macOS NowPlaying y RemoteCommandCenter nativos (PyObjC)
theiaplayer/art.py         widget CoverArt, detección de protocolo (kitty/sixel/halfcell)
theiaplayer/screens.py     onboarding, SearchModal, InputModal, LyricsModal
theiaplayer/models.py      dataclasses Song/Album/Artist/Playlist con to_dict/from_dict
tools/screenshots.py   generador SVG headless + FakeClient (sin red, sin datos reales)
tools/demo.py          posa el app real para capturas (main/playlist/search/void)
```

## Prioridades de diseño (del upstream, mantener)

1. **fast** — cache-first; la UI nunca bloquea en red
2. **alive** — un heartbeat a 8fps maneja TODA la animación; nunca agregar timer por widget
3. **pretty** — temas ricekit en render time; iconos nerd-font como `\uXXXX`, nunca glifos raw PUA

## Bordes afilados

| Gotcha | Regla |
|---|---|
| Callbacks de mpv | Llegan en el thread de mpv — nunca bloquear. Usar `loop.call_soon_threadsafe` (no `call_from_thread` — deadlock contra `terminate()`). Ver `_mpv_position`/`_mpv_track_end` en app.py |
| `_want_playing` flag | Player.py usa este flag para ignorar eventos `end-file` de tracks que se reemplazaron — no sacarlo |
| Temas ANSI (`system`) | `anim.blend`/`can_blend()` degrada a estilos planos cuando no hay RGB — nunca hardcodear colores de palette al importar |
| Textual action args | Son literales Python: `enqueue(True)`, nunca `enqueue(true)` |
| `ricekit` | Micro-paquete de diseño embebido y absorbido localmente en la raíz como `/ricekit/` para simplificar la arquitectura, acelerar el desarrollo y lograr un Monorepo-lite 100% autocontenido y reproducible sin dependencias Git de terceros en el TOML. |
| `_MprisService` en mpris.py | La clase hereda de `dbus.service.Object` — se define dentro de `_define_service()` para evitar `NameError` cuando `dbus-python` no está instalado |
| BINDINGS dinámicos | `TheIAPlayerApp.BINDINGS` se parchea en `__init__` ANTES de `super().__init__()`. Mutación de clase aceptable porque es app single-instance |
| `_pcfg` en `__init__` | Config cargada antes de `super().__init__()` y guardada como `self._pcfg`. No recargar en `on_mount` |
| Filtros en `_show_songs` | `_apply_filters()` opera sobre la lista raw. La lista `self._songs` YA está filtrada — no filtrar de nuevo en `_song_row` |
| Hilos en `dbus-python` | `dbus-python` requiere de forma obligatoria la llamada `dbus.mainloop.glib.threads_init()` en el hilo principal antes de instanciar `dbus.SessionBus()` en hilos secundarios de Python. Omitirlo provoca un deadlock síncrono infinito en C que congela la app en negro al iniciar. |
| Escritura de Wrappers | Al escribir archivos en `~/.local/bin/` que previamente eran enlaces simbólicos, Python sigue el enlace físico sobreescribiendo el binario del venv (provocando loops infinitos de Bash). Se debe borrar físicamente con `rm -f` cualquier enlace simbólico previo antes de escribir archivos planos. |
| Negociación en Ghostty | La negociación interactiva de capacidades ANSI de `textual-image` con la TTY física real puede dar timeouts. Para Ghostty, la forma óptima y 100% estable es forzar de forma nativa `NAVITUI_ART=tgp` directamente en Python en `app.py:main()`, evitando shells intermedias de Bash que interfieran en el socket TTY. |

## Configuración (player.toml)

`~/.config/theia-player/player.toml` — se genera con valores comentados al primer arranque.

Secciones disponibles:

```toml
# Playback
replaygain = "album"   # track | album | no
gapless    = "yes"     # yes | no | weak
default_volume = 80
replaygain_preamp = 4   # preamp base gain in dB (default: 0)
replaygain_fallback = -6 # fallback gain in dB if no metadata exists (default: -6)

# Integraciones
desktop_notifications = true
discord_rich_presence  = false
discord_app_id         = ""    # discord.com/developers/applications

# [keybinds]  — 34 acciones configurables (ver config.py DEFAULT_KEYBINDS)
# [filters]   — excluir por título/artista/género/duración/play_count
# [columns]   — activar/desactivar campos en la fila de cada track
```

## Dependencias opcionales

```bash
# MPRIS2 (control de escritorio en Linux/FreeBSD)
pip install dbus-python
# o: pip install ".[mpris]"

# macOS Media Controls (teclas de Apple, Centro de Control de macOS)
pip install pyobjc-framework-MediaPlayer
# o: pip install ".[mac]"

# Discord Rich Presence
pip install pypresence
# o: pip install ".[discord]"

# Todo junto (instala automáticamente pyobjc si estás en Mac, o dbus si estás en Linux)
pip install ".[full]"
```

## Correr en desarrollo

### Atajos de ejecución global (Recomendado)
Se han instalado enlaces simbólicos en `~/.local/bin/` (dentro del PATH de usuario), por lo que puedes abrir el reproductor al instante desde cualquier directorio en tu terminal usando:
```bash
tp
# o bien:
theia-player
```

### Ejecución manual tradicional
```bash
cd /home/rodmera/projects/theia-player
.venv/bin/python3 -m navitui
# o:
.venv/bin/theia-player
```

Conecta a Navidrome local: `localhost:4533` / usuario `rodmera`.

```bash
# Instalar dependencias (ya hecho, venv en .venv/)
python3 -m venv .venv && .venv/bin/pip install -e ".[full]"
```

## Features implementadas

| Feature | Archivo | Notas |
|---|---|---|
| ReplayGain album/track/no | `player.py`, `config.py` | Configurable en player.toml |
| Preamp & RG Ganancia | `player.py`, `config.py`, `app.py` | Configurable nativamente en player.toml (`replaygain_preamp` / `replaygain_fallback`) |
| Gapless playback | `player.py`, `config.py` | Configurable en player.toml |
| MPRIS2 D-Bus (Linux) | `mpris.py` | Opcional (dbus-python). Soporta control bidireccional de reproducción completo (Play, Pause, PlayPause, Next, Previous) desde el entorno de escritorio y teclas multimedia del teclado de forma segura para hilos. |
| NowPlaying (macOS Cocoa) | `nowplaying_mac.py` | Opcional (`pyobjc-framework-MediaPlayer`). Soporta integración nativa y de hilos asíncrona de 1:1 con las teclas físicas de Apple (F7/F8/F9), carátulas dinámicas desde disco y el Centro de Sonido de tu Mac. |
| Desktop notifications | `app.py`, `config.py`, `widgets.py` | `notify-send` con cover art; toggle `N` visible en footer. Soportado el modo silencioso, mostrando un indicador estático `[Silent]` a color en la barra de reproducción si las notificaciones de escritorio se desactivan. |
| Discord Rich Presence | `discord_rpc.py` | Opcional: requiere `pypresence` + app_id |
| Keybinds configurables | `config.py`, `app.py` | `[keybinds]` en player.toml — 34 acciones |
| Queue reorder | `playqueue.py`, `app.py` | `ctrl+↑`/`ctrl+↓` en queue panel |
| Share link | `api.py`, `app.py` | `S` — llama `createShare`, copia al clipboard |
| Rating 1-5 | `api.py`, `models.py`, `app.py` | Teclas `1`-`5` en tracks panel; `0` borra |
| Letras Sincronizadas (Lyrics) | `api.py`, `screens.py`, `app.py` | `L` — Detección automática de formato LRC (sincronizado por milisegundos). Resalta y desplaza verticalmente (scroll suave) en tiempo real siguiendo la reproducción real de mpv. |
| Modo de Escucha Privado | `app.py`, `api.py` | `P` — Toggle global. Desactiva temporalmente el scrobbling al servidor Navidrome y muestra el indicador visual `[Private]` en magenta en la barra de estado. |
| Auto DJ (Infinite Autoplay) | `app.py`, `config.py` | Cuando la cola tiene <= 1 canción restante, realiza una precarga asíncrona de 15 canciones aleatorias del servidor. Configurable en player.toml. |
| Filtro de Discografía por Release Type | `app.py`, `models.py` | `alt+a` (Álbumes), `alt+s` (Singles & EPs), `alt+o` (Todo) — Filtra en memoria y en caliente la discografía del artista en la vista de artistas sin latencia de red. |
| Caché Offline de Audio (Offline Audio Cache) | `app.py`, `config.py` | Descarga de fondo en chunks asíncronos (`httpx`) de archivos de música a `~/.cache/theia-player/audio/` y priorización local ante reproducción; rotación inteligente LRU por cuota de disco configurable. |
| Vista de Inicio Inteligente (Home Dashboard) | `app.py` | Vista `home` con nodo `🏠 home` en sidebar que reúne recomendaciones, pistas frecuentes e incorporaciones nuevas en un solo mix dinámico sin duplicados. |
| Soporte Multi-Servidor (Profile Switcher) | `app.py`, `screens.py` | `ctrl+s` — Modal interactivo de cambio de servidor en caliente con reconexión de cliente Subsonic y flushing seguro de cola para evitar cruce de tracks. |
| Agrupación de Playlists en Carpetas | `app.py` | Detección de `/` en los nombres de playlists en el sidebar para agruparlas cosméticamente bajo cabeceras destacadas e indentación visual. |
| Selección de Dispositivo de Audio (Device Switcher) | `app.py`, `screens.py`, `player.py` | `ctrl+d` — Modal interactivo que consulta `audio-device-list` de `mpv` en tiempo real y te permite alternar en caliente y en tiempo real tu dispositivo de salida de audio (parlante, DAC BT, audífonos Jack); persiste la preferencia en estado. |
| Go to album / artist | `app.py` | `e` / `E` desde cualquier track |
| Multi-selección | `app.py` | `v` toggle; `a`/`A`/`f` operan sobre todos |
| Filtros de biblioteca | `config.py`, `app.py` | `[filters]` en player.toml |
| Columnas configurables | `config.py`, `app.py` | `[columns]` en player.toml |

## Suite de Pruebas TUI / Integración

El proyecto cuenta con un validador automatizado en modo headless que ejecuta una simulación interactiva real presionando teclas, simulando flujos asíncronos y exportando capturas visuales en SVG y PNG en `/assets/` para confirmar que no haya excepciones o congelamientos en el inicio:

```bash
.venv/bin/python tools/screenshots.py
```

*Nota técnica: Se corrigió quirúrgicamente un bug heredado en este script, actualizando la selección de foco al ID correcto (`#pane1-list` → `#sidebar-list`). La suite ahora pasa limpia con código de salida `0` (exit 0).*

## Compilación, Automatización y Versionado Autónomo (DevOps Pipeline)

El versionamiento y empaquetado del reproductor es administrado de forma **autónoma e inteligente por la IA (el Agente)** mediante Integración y Entrega Continua (CI/CD):

1.  **Versionado Semántico (SemVer):** Al completarse un hito estable de desarrollo, la versión del código se incrementa en `theiaplayer/__init__.py` (variable `__version__`) y se sincroniza en `pyproject.toml`.
2.  **Etiquetas de Git (Tags):** La IA crea y empuja de forma local y remota la etiqueta correspondiente (ej. `v1.0.0`) de forma directa:
    ```bash
    git tag -a v1.0.0 -m "Release v1.0.0: first stable production release"
    git push origin v1.0.0
    ```
3.  **Compilación en la Nube (GitHub Actions):** El archivo `.github/workflows/release.yaml` se ejecuta de forma asíncrona ante el push de cualquier tag `v*`, aprovisionando runners de Linux y macOS para compilar los ejecutables nativos mediante PyInstaller:
    *   **Linux (amd64):** Binario autocontenido nativo ELF `theia-player-linux-amd64`.
    *   **macOS (arm64):** Binario autocontenido nativo Mach-O `theia-player-macos-arm64` (optimizado para Apple Silicon).
4.  **Generación de Releases:** Al finalizar con éxito el build, el pipeline publica automáticamente la Release en tu GitHub y le adjunta de forma segura ambos binarios para su descarga instantánea.

## Actualizar desde upstream

```bash
git fetch upstream
git merge upstream/main
# resolver conflictos si los hay, luego:
git push origin main
```
