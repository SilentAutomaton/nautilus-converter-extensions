# Nautilus converter extensions

[English](README.en.md)

Набор расширений для файлового менеджера Nautilus. Добавляет пункты в контекстное меню
для конвертации медиафайлов и работы с правами администратора.

Изначально расширения были созданы для включения в дистрибутив МСВСфера.

## Расширения

- **nautilus-video-converter** — конвертация видео (CRF, пресет, разрешение, битрейт).
- **nautilus-audio-converter** — конвертация аудио в MP3, OGG, WAV, FLAC.
- **nautilus-image-converter** — конвертация изображений в JPG, PNG, BMP, TIFF, WEBP.
- **nautilus-video-audio-streams** — извлечение аудио- и видеодорожек и обратное объединение.
- **nautilus-subtitle-combiner** — встраивание файлов субтитров в видео.
- **nautilus-pdf-converter** — разбор PDF на изображения и сборка изображений в PDF.
- **nautilus-admin** — открытие папок и текстовых файлов с правами администратора.

## Зависимости

ffmpeg, ImageMagick, qpdf, nautilus-python, python3-gobject

## Установка

```bash
cp extensions/*.py ~/.local/share/nautilus-python/extensions/
nautilus -q
```

## Лицензия

GPLv3 — см. [LICENSE](LICENSE).
