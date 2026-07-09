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
navitui/app.py        layout, workers, playback glue, keybindings
navitui/api.py        cliente async Subsonic (httpx), token auth, cache de covers
navitui/player.py     wrapper libmpv + NullPlayer fallback si mpv no está
navitui/playqueue.py  lógica de cola/shuffle/repeat — sin UI, puro lógica
navitui/anim.py       primitivas de animación: shimmer, smooth_bar, marquee, viz
navitui/widgets.py    Logo, Visualizer, NowPlaying (transport animado)
navitui/art.py        widget CoverArt, detección de protocolo (kitty/sixel/halfcell)
navitui/screens.py    onboarding, modal de búsqueda, InputModal (nombres playlist)
navitui/models.py     dataclasses Song/Album/Artist/Playlist con to_dict/from_dict
tools/screenshots.py  generador SVG headless + FakeClient (sin red, sin datos reales)
tools/demo.py         posa el app real para capturas (main/playlist/search/void)
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

## Dependencias a instalar

```bash
# Arch (sistema de Rodrigo)
sudo pacman -S mpv

# Python
uv tool install -e /home/rodmera/projects/theia-player
# o en desarrollo:
cd /home/rodmera/projects/theia-player
pip install -e .
```

## Correr en desarrollo

```bash
cd /home/rodmera/projects/theia-player
python3 -m navitui
# o con audio null para tests:
# NAVITUI_ART=off python3 -m navitui  (sin cover art)
```

Conecta a Navidrome local: `localhost:4533` / usuario `rodmera`.

## Features pendientes vs SubTUI (backlog)

| Feature | Estado | Notas |
|---|---|---|
| **ReplayGain por álbum** | pendiente | Agregar `replaygain="album"` a opts mpv en `player.py:64` |
| **Gapless playback** | pendiente | Agregar `gapless_audio=True` a opts mpv en `player.py:64` |
| **MPRIS** | pendiente | `dbus-python` + mpris2; permite control desde widgets del DE |

## Actualizar desde upstream

```bash
git fetch upstream
git merge upstream/main
# resolver conflictos si los hay, luego:
git push origin main
```
