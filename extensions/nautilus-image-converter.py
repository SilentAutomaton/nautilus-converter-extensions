from gi.repository import Nautilus, GObject, Gtk, GLib
import subprocess
import os
import threading
import queue
from common import setup_localisation

_ = setup_localisation()


class ImageConverterWindow(Gtk.Window):
    def __init__(self, files, fmt):
        super().__init__(title=_("Image Converter"))
        self.files = files
        self.fmt = fmt
        self.set_default_size(400, 100)
        self.proc = None
        self.stop_requested = False
        self._queue = queue.Queue()
        self._thread_done = False
        self.connect("destroy", self.on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        self.label = Gtk.Label(label=_("Converting {0} files to {1}...").format(len(files), fmt.upper()))
        vbox.append(self.label)

        self.progress_bar = Gtk.ProgressBar()
        vbox.append(self.progress_bar)

        self.thread = threading.Thread(target=self.convert_files, daemon=True)
        self.thread.start()
        self.add_tick_callback(self._tick_poll)

    def on_destroy(self, widget):
        self.stop_requested = True
        if self.proc:
            self.proc.terminate()

    def _tick_poll(self, widget, frame_clock):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == 'fraction':
                    self.progress_bar.set_fraction(msg[1])
                elif kind == 'label':
                    self.label.set_text(msg[1])
                elif kind == 'close':
                    GLib.timeout_add(1500, self.close)
        except queue.Empty:
            pass

        if self._thread_done and self._queue.empty():
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def convert_files(self):
        for i, file in enumerate(self.files):
            if self.stop_requested:
                self._thread_done = True
                return

            input_path = file.get_location().get_path()
            base, ext = os.path.splitext(input_path)
            if ext.lstrip('.').lower() == self.fmt.lower():
                output_path = f'{base}_converted.{self.fmt}'
            else:
                output_path = f'{base}.{self.fmt}'

            try:
                proc = subprocess.Popen(
                    ['convert', input_path, output_path],
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                )
                self.proc = proc
                _stdout, stderr_output = proc.communicate()

                if proc.returncode != 0:
                    self._queue.put(('label', _("Error: {0}").format(
                        stderr_output.strip() or f"exit code {proc.returncode}")))
                    self._thread_done = True
                    return

            except (OSError, FileNotFoundError) as e:
                self._queue.put(('label', _("Error: {0}").format(str(e))))
                self._thread_done = True
                return

            self._queue.put(('fraction', (i + 1) / len(self.files)))

        self._queue.put(('label', _("Done!")))
        self._queue.put(('close', None))
        self._thread_done = True


class ImageConverterExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('image/'):
                return []

        submenu = Nautilus.Menu()

        item = Nautilus.MenuItem(
            name='ImageConverterExtension::Convert',
            label=_('Convert to'),
            tip=_('Converts selected image(s) to a different format')
        )
        item.set_submenu(submenu)

        mime_types = {file.get_mime_type() for file in files}

        excluded_fmt = None
        if len(mime_types) == 1:
            mime_type = mime_types.pop()
            mime_to_fmt = {
                'image/jpeg': 'JPG',
                'image/png': 'PNG',
                'image/bmp': 'BMP',
                'image/tiff': 'TIFF',
                'image/webp': 'WEBP',
            }
            excluded_fmt = mime_to_fmt.get(mime_type)

        formats = ['JPG', 'PNG', 'BMP', 'TIFF', 'WEBP']

        for fmt in formats:
            if fmt != excluded_fmt:
                self._add_submenu_item(submenu, fmt, files)

        return [item]

    def _add_submenu_item(self, submenu, fmt, files):
        item = Nautilus.MenuItem(
            name=f'ImageConverterExtension::Convert::{fmt}',
            label=fmt,
            tip=_('Convert to {0}').format(fmt)
        )
        item.connect('activate', self._show_converter_window, files, fmt.lower())
        submenu.append_item(item)

    def _show_converter_window(self, menu, files, fmt):
        win = ImageConverterWindow(files, fmt)
        win.set_visible(True)
