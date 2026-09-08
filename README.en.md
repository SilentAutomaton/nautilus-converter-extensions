# Nautilus converter extensions

[Russian](README.md)

A set of extensions for the Nautilus file manager. They add context menu items
for media file conversion and for admin privilege operations.

The extensions were initially made for inclusion in MSVSphere, a Russian Linux distribution.

## Extensions

- **nautilus-video-converter** — video conversion (CRF, preset, resolution, bitrate).
- **nautilus-audio-converter** — audio conversion to MP3, OGG, WAV, FLAC.
- **nautilus-image-converter** — image conversion to JPG, PNG, BMP, TIFF, WEBP.
- **nautilus-video-audio-streams** — extraction of audio and video tracks, and the reverse merge.
- **nautilus-subtitle-combiner** — embedding of subtitle files into video.
- **nautilus-pdf-converter** — split of a PDF into images, and build of images into a PDF.
- **nautilus-admin** — open folders and text files with admin privileges.

## Dependencies

ffmpeg, ImageMagick, qpdf, nautilus-python, python3-gobject

## Installation

```bash
cp extensions/*.py ~/.local/share/nautilus-python/extensions/
nautilus -q
```

## Repository layout

```
extensions/common.py   shared code: the ffmpeg worker thread (class FFmpeg)
                       and the progress window (BaseConverterWindow)
extensions/nautilus-*.py   one extension per file
po/                    translations (gettext, domain msvsphere-nautilus-extensions)
test_extensions.py     self-checks: MIME detection and ffmpeg output reading
```

Each extension subclasses `BaseConverterWindow` and gives `_start_ffmpeg` a list
of jobs together with a command builder. Change `common.py` when a bug concerns
progress reporting or the ffmpeg run: that code is shared by every extension.

Compare MIME types with `Gio.content_type_is_a`, not with a string:
`shared-mime-info` renamed `video/x-matroska` to `video/matroska`, and the old
name is now only an alias.

## Checks

```bash
python3 test_extensions.py
```

## License

GPLv3 — see [LICENSE](LICENSE).
