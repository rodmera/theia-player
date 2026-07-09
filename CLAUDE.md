# CLAUDE.md — theia-player

Fork de [NaviTui](https://github.com/Gheat1/NaviTui). TUI music player para Navidrome/Subsonic, escrito en Python con Textual + libmpv.

**Repo:** `github.com/rodmera/theia-player`
**Upstream:** `github.com/Gheat1/NaviTui` (remote `upstream`) — hacer `git fetch upstream` para traer cambios futuros

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
navitui/app.py         layout, workers, playback glue, keybindings
navitui/api.py         cliente async Subsonic (httpx), token auth, cache de covers
navitui/player.py      wrapper libmpv + NullPlayer fallback si mpv no está
navitui/playqueue.py   lógica de cola/shuffle/repeat — sin UI, puro lógica
navitui/config.py      carga player.toml; build_bindings() genera BINDINGS desde config
navitui/mpris.py       MPRIS2 D-Bus bidireccional (dbus-python); GLib loop en hilo daemon
navitui/discord_rpc.py Discord Rich Presence via pypresence; no-op si no está instalado
navitui/anim.py        primitivas de animación: shimmer, smooth_bar, marquee, viz
navitui/widgets.py     Logo, Visualizer, NowPlaying (transport animado)
navitui/art.py         widget CoverArt, detección de protocolo (kitty/sixel/halfcell)
navitui/screens.py     onboarding, SearchModal, InputModal, LyricsModal
navitui/models.py      dataclasses Song/Album/Artist/Playlist con to_dict/from_dict
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
| `ricekit` | Dependencia forqueada a `rodmera/ricekit` en `pyproject.toml` para garantizar reproducibilidad absoluta y blindaje ante cambios externos. |
| `_MprisService` en mpris.py | La clase hereda de `dbus.service.Object` — se define dentro de `_define_service()` para evitar `NameError` cuando `dbus-python` no está instalado |
| BINDINGS dinámicos | `NaviTuiApp.BINDINGS` se parchea en `__init__` ANTES de `super().__init__()`. Mutación de clase aceptable porque es app single-instance |
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
# MPRIS2 (control desde widgets del DE, playerctl, etc.)
pip install dbus-python
# o: pip install ".[mpris]"

# Discord Rich Presence
pip install pypresence
# o: pip install ".[discord]"

# Todo junto
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
| MPRIS2 D-Bus | `mpris.py` | Opcional (dbus-python). Soporta control bidireccional de reproducción completo (Play, Pause, PlayPause, Next, Previous) desde el entorno de escritorio y teclas multimedia del teclado de forma segura para hilos. |
| Desktop notifications | `app.py`, `config.py`, `widgets.py` | `notify-send` con cover art; toggle `N` visible en footer. Soportado el modo silencioso, mostrando un indicador estático `[Silent]` a color en la barra de reproducción si las notificaciones de escritorio se desactivan. |
| Discord Rich Presence | `discord_rpc.py` | Opcional: requiere `pypresence` + app_id |
| Keybinds configurables | `config.py`, `app.py` | `[keybinds]` en player.toml — 34 acciones |
| Queue reorder | `playqueue.py`, `app.py` | `ctrl+↑`/`ctrl+↓` en queue panel |
| Share link | `api.py`, `app.py` | `S` — llama `createShare`, copia al clipboard |
| Rating 1-5 | `api.py`, `models.py`, `app.py` | Teclas `1`-`5` en tracks panel; `0` borra |
| Letras (lyrics) | `api.py`, `screens.py`, `app.py` | `L` — overlay scrollable, j/k para navegar |
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

## Actualizar desde upstream

```bash
git fetch upstream
git merge upstream/main
# resolver conflictos si los hay, luego:
git push origin main
```
