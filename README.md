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

## Структура репозитория

```
extensions/common.py   общий код: запуск ffmpeg в потоке (класс FFmpeg)
                       и окно с полосой прогресса (BaseConverterWindow)
extensions/nautilus-*.py   по одному расширению на файл
po/                    переводы (gettext, домен msvsphere-nautilus-extensions)
test_extensions.py     самопроверки: определение MIME-типа и чтение вывода ffmpeg
```

Каждое расширение наследует `BaseConverterWindow` и передаёт в `_start_ffmpeg`
список задач вместе со сборщиком команды. Правьте `common.py`, если ошибка
касается прогресса или запуска ffmpeg: этот код общий для всех расширений.

Тип MIME сравнивайте через `Gio.content_type_is_a`, а не строкой:
`shared-mime-info` переименовал `video/x-matroska` в `video/matroska`,
и старое имя осталось только псевдонимом.

## Проверка

```bash
python3 test_extensions.py
```

## Лицензия

GPLv3 — см. [LICENSE](LICENSE).
