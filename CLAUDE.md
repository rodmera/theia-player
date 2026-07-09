# CLAUDE.md — theia-player

Fork de [NaviTui](https://github.com/Gheat1/NaviTui). TUI music player para Navidrome/Subsonic, escrito en Python con Textual + libmpv.

**Repo:** `github.com/rodmera/theia-player`
**Upstream:** `github.com/Gheat1/NaviTui` (remote `upstream`) — hacer `git fetch upstream` para traer cambios futuros

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
navitui/mpris.py       MPRIS2 D-Bus via dbus-python; GLib loop en hilo daemon
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
| `ricekit` | Dependencia externa de `Gheat1/ricekit`. Si el upstream cambia la API, puede romper. Considerar fork si hay cambios disruptivos |
| `_MprisService` en mpris.py | La clase hereda de `dbus.service.Object` — se define dentro de `_define_service()` para evitar `NameError` cuando `dbus-python` no está instalado |
| BINDINGS dinámicos | `NaviTuiApp.BINDINGS` se parchea en `__init__` ANTES de `super().__init__()`. Mutación de clase aceptable porque es app single-instance |
| `_pcfg` en `__init__` | Config cargada antes de `super().__init__()` y guardada como `self._pcfg`. No recargar en `on_mount` |
| Filtros en `_show_songs` | `_apply_filters()` opera sobre la lista raw. La lista `self._songs` YA está filtrada — no filtrar de nuevo en `_song_row` |

## Configuración (player.toml)

`~/.config/theia-player/player.toml` — se genera con valores comentados al primer arranque.

Secciones disponibles:

```toml
# Playback
replaygain = "album"   # track | album | no
gapless    = "yes"     # yes | no | weak
default_volume = 80

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
| Gapless playback | `player.py`, `config.py` | Configurable en player.toml |
| MPRIS2 D-Bus | `mpris.py` | Opcional: requiere `dbus-python` |
| Desktop notifications | `app.py` | `notify-send` con cover art; toggle `N` |
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

## Actualizar desde upstream

```bash
git fetch upstream
git merge upstream/main
# resolver conflictos si los hay, luego:
git push origin main
```
