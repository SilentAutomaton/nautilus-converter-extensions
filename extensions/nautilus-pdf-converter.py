from gi.repository import Nautilus, GObject, Gtk, GLib
import subprocess
import os
import threading
import tempfile
import shutil
import glob
import queue
from common import setup_localisation

_ = setup_localisation()


# ─── PDF → Images ────────────────────────────────────────────────────────────

class PdfToImagesWindow(Gtk.Window):
    FORMATS = ['PNG', 'JPG']
    DPIS = ['150', '300', '600']

    def __init__(self, files):
        super().__init__(title=_("PDF to Images"))
        self.files = files
        self.set_default_size(360, 220)
        self.current_proc = None
        self.stop_requested = False
        self._queue = queue.Queue()
        self._thread_done = False
        self.connect("destroy", self.on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        vbox.append(grid)

        label_fmt = Gtk.Label(label=_("Output Format:"))
        label_fmt.set_halign(Gtk.Align.START)
        grid.attach(label_fmt, 0, 0, 1, 1)

        self.fmt_combo = Gtk.ComboBoxText()
        for fmt in self.FORMATS:
            self.fmt_combo.append_text(fmt)
        self.fmt_combo.set_active(0)  # PNG
        grid.attach(self.fmt_combo, 1, 0, 1, 1)

        label_dpi = Gtk.Label(label=_("Resolution (DPI):"))
        label_dpi.set_halign(Gtk.Align.START)
        grid.attach(label_dpi, 0, 1, 1, 1)

        self.dpi_combo = Gtk.ComboBoxText()
        for dpi in self.DPIS:
            self.dpi_combo.append_text(dpi)
        self.dpi_combo.set_active(1)  # 300
        grid.attach(self.dpi_combo, 1, 1, 1, 1)

        self.action_button = Gtk.Button(label=_("Convert"))
        self.action_button.get_style_context().add_class("suggested-action")
        self.action_button.connect("clicked", self.on_convert_clicked)
        vbox.append(self.action_button)

        self.status_label = Gtk.Label()
        vbox.append(self.status_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        vbox.append(self.progress_bar)

    def on_destroy(self, widget):
        self.stop_requested = True
        if self.current_proc:
            self.current_proc.terminate()

    def on_convert_clicked(self, widget):
        self.action_button.set_sensitive(False)
        fmt = self.fmt_combo.get_active_text().lower()
        dpi = self.dpi_combo.get_active_text()
        self.progress_bar.set_visible(True)
        self.status_label.set_text(_("Converting..."))

        self._thread_done = False
        thread = threading.Thread(target=self.convert_files, args=(fmt, dpi), daemon=True)
        thread.start()
        self.add_tick_callback(self._tick_poll)

    def _tick_poll(self, widget, frame_clock):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == 'fraction':
                    self.progress_bar.set_fraction(msg[1])
                elif kind == 'status':
                    self.status_label.set_text(msg[1])
                elif kind == 'done':
                    self._on_done()
        except queue.Empty:
            pass

        if self._thread_done and self._queue.empty():
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def convert_files(self, fmt, dpi):
        total = len(self.files)
        for i, file in enumerate(self.files):
            if self.stop_requested:
                self._thread_done = True
                return

            input_path = file.get_location().get_path()
            base = os.path.splitext(input_path)[0]
            tmpdir = tempfile.mkdtemp(prefix='nautilus_pdf_')

            try:
                # Step 1: split PDF into individual page PDFs with qpdf
                split_result = subprocess.run(
                    ['qpdf', '--split-pages', input_path,
                     os.path.join(tmpdir, 'page_%d.pdf')],
                    capture_output=True, text=True
                )
                if split_result.returncode != 0:
                    err = split_result.stderr.strip() or f"exit code {split_result.returncode}"
                    self._queue.put(('status', _("Error: {0}").format(err)))
                    self._thread_done = True
                    return

                page_pdfs = sorted(glob.glob(os.path.join(tmpdir, 'page_*.pdf')))
                total_pages = len(page_pdfs)
                if total_pages == 0:
                    self._queue.put(('status', _("Error: No pages found in PDF.")))
                    self._thread_done = True
                    return

                # Step 2: convert each page PDF to image with ImageMagick
                for j, page_pdf in enumerate(page_pdfs):
                    if self.stop_requested:
                        self._thread_done = True
                        return

                    page_num = j + 1
                    output_img = f"{base}_page_{page_num:04d}.{fmt}"

                    proc = subprocess.Popen(
                        ['convert', '-density', dpi, page_pdf, output_img],
                        stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                        universal_newlines=True, encoding='utf-8',
                    )
                    self.current_proc = proc
                    _stdout, stderr = proc.communicate()

                    if proc.returncode != 0:
                        err = stderr.strip() or f"exit code {proc.returncode}"
                        self._queue.put(('status', _("Error: {0}").format(err)))
                        self._thread_done = True
                        return

                    overall = (i * total_pages + page_num) / (total * total_pages)
                    self._queue.put(('fraction', overall))

            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        self._queue.put(('done', None))
        self._thread_done = True

    def _on_done(self):
        self.progress_bar.set_fraction(1.0)
        self.status_label.set_text(_("Done!"))
        self.action_button.set_label(_("Close"))
        self.action_button.set_sensitive(True)
        self.action_button.disconnect_by_func(self.on_convert_clicked)
        self.action_button.connect("clicked", lambda w: self.close())


# ─── Images → PDF ────────────────────────────────────────────────────────────

class ImagesToPdfWindow(Gtk.Window):
    DPIS = ['72', '150', '300', '600']

    def __init__(self, files):
        super().__init__(title=_("Images to PDF"))
        self.files = files
        self.set_default_size(360, 200)
        self.current_proc = None
        self.stop_requested = False
        self._queue = queue.Queue()
        self._thread_done = False
        self.connect("destroy", self.on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        vbox.append(grid)

        label_dpi = Gtk.Label(label=_("Resolution (DPI):"))
        label_dpi.set_halign(Gtk.Align.START)
        grid.attach(label_dpi, 0, 0, 1, 1)

        self.dpi_combo = Gtk.ComboBoxText()
        for dpi in self.DPIS:
            self.dpi_combo.append_text(dpi)
        self.dpi_combo.set_active(2)  # 300
        grid.attach(self.dpi_combo, 1, 0, 1, 1)

        self.action_button = Gtk.Button(label=_("Combine"))
        self.action_button.get_style_context().add_class("suggested-action")
        self.action_button.connect("clicked", self.on_combine_clicked)
        vbox.append(self.action_button)

        self.status_label = Gtk.Label(
            label=_("{0} images selected").format(len(files))
        )
        vbox.append(self.status_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        vbox.append(self.progress_bar)

    def on_destroy(self, widget):
        self.stop_requested = True
        if self.current_proc:
            self.current_proc.terminate()

    def on_combine_clicked(self, widget):
        self.action_button.set_sensitive(False)
        dpi = self.dpi_combo.get_active_text()
        self.progress_bar.set_visible(True)
        self.status_label.set_text(_("Converting..."))

        self._thread_done = False
        thread = threading.Thread(target=self.convert_files, args=(dpi,), daemon=True)
        thread.start()
        self.add_tick_callback(self._tick_poll)

    def _unique_output_path(self, directory, stem):
        path = os.path.join(directory, f"{stem}.pdf")
        if not os.path.exists(path):
            return path
        counter = 1
        while True:
            path = os.path.join(directory, f"{stem}_{counter}.pdf")
            if not os.path.exists(path):
                return path
            counter += 1

    def _tick_poll(self, widget, frame_clock):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == 'fraction':
                    self.progress_bar.set_fraction(msg[1])
                elif kind == 'status':
                    self.status_label.set_text(msg[1])
                elif kind == 'done':
                    self._on_done(msg[1])
        except queue.Empty:
            pass

        if self._thread_done and self._queue.empty():
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _on_done(self, saved_text):
        self.progress_bar.set_fraction(1.0)
        self.status_label.set_text(saved_text)
        self.action_button.set_label(_("Close"))
        self.action_button.set_sensitive(True)
        self.action_button.disconnect_by_func(self.on_combine_clicked)
        self.action_button.connect("clicked", lambda w: self.close())

    def convert_files(self, dpi):
        sorted_files = sorted(self.files, key=lambda f: f.get_name())
        input_paths = [f.get_location().get_path() for f in sorted_files]

        first_dir = os.path.dirname(input_paths[0])
        dir_name = os.path.basename(first_dir) or "output"
        output_path = self._unique_output_path(first_dir, dir_name)

        tmpdir = tempfile.mkdtemp(prefix='nautilus_img2pdf_')
        try:
            # Step 1: convert each image to a single-page PDF with ImageMagick
            page_pdfs = []
            for i, img_path in enumerate(input_paths):
                if self.stop_requested:
                    self._thread_done = True
                    return

                page_pdf = os.path.join(tmpdir, f"page_{i:04d}.pdf")
                proc = subprocess.Popen(
                    ['convert', '-density', dpi, img_path, page_pdf],
                    stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                    universal_newlines=True, encoding='utf-8',
                )
                self.current_proc = proc
                _stdout, stderr = proc.communicate()

                if proc.returncode != 0:
                    err = stderr.strip() or f"exit code {proc.returncode}"
                    self._queue.put(('status', _("Error: {0}").format(err)))
                    self._thread_done = True
                    return

                page_pdfs.append(page_pdf)
                self._queue.put(('fraction', (i + 1) / len(input_paths) * 0.8))

            if self.stop_requested:
                self._thread_done = True
                return

            # Step 2: combine page PDFs into final PDF with qpdf
            qpdf_cmd = ['qpdf', '--empty', '--pages'] + page_pdfs + ['--', output_path]
            proc = subprocess.Popen(
                qpdf_cmd,
                stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                universal_newlines=True, encoding='utf-8',
            )
            self.current_proc = proc
            _stdout, stderr = proc.communicate()

            if proc.returncode != 0:
                err = stderr.strip() or f"exit code {proc.returncode}"
                self._queue.put(('status', _("Error: {0}").format(err)))
                self._thread_done = True
                return

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self._queue.put(('done', _("Done! Saved: {0}").format(os.path.basename(output_path))))
        self._thread_done = True


# ─── Nautilus Extension Classes ───────────────────────────────────────────────

class PdfToImagesExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if file.get_mime_type() != 'application/pdf':
                return []

        item = Nautilus.MenuItem(
            name='PdfToImagesExtension::Split',
            label=_('Split PDF to Images'),
            tip=_('Convert each PDF page to a separate image file')
        )
        item.connect('activate', self.show_window, files)

        return [item]

    def show_window(self, menu, files):
        win = PdfToImagesWindow(files)
        win.set_visible(True)


class ImagesToPdfExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if not files:
            return []

        for file in files:
            if not file.get_mime_type().startswith('image/'):
                return []

        item = Nautilus.MenuItem(
            name='ImagesToPdfExtension::Combine',
            label=_('Combine to PDF'),
            tip=_('Combine selected images into a single PDF file')
        )
        item.connect('activate', self.show_window, files)

        return [item]

    def show_window(self, menu, files):
        win = ImagesToPdfWindow(files)
        win.set_visible(True)
