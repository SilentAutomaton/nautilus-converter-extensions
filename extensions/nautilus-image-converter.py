from gi.repository import Nautilus, GObject, Gtk, GLib
import subprocess
import os
import sys
import threading
from common import setup_localisation, Popen

_ = setup_localisation()

class ImageConverterWindow(Gtk.ApplicationWindow):
    def __init__(self, files, format, app):
        super().__init__(title=_("Image Converter"), application=app)
        self.files = files
        self.format = format
        self.set_default_size(400, 100)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.set_child(vbox)

        self.label = Gtk.Label(label=_("Converting {0} files to {1}...").format(len(files), format.upper()))
        vbox.append(self.label)

        self.progress_bar = Gtk.ProgressBar()
        vbox.append(self.progress_bar)

        self.thread = threading.Thread(target=self.convert_files)
        self.thread.start()

    def convert_files(self):
        for i, file in enumerate(self.files):
            input_path = file
            output_path = os.path.splitext(input_path)[0] + f'.{self.format}'
            
            try:
                with Popen(['convert', input_path, output_path],
                                 stderr=subprocess.PIPE,
                                 stdin=subprocess.PIPE,
                                 bufsize=1,
                                 universal_newlines=True,
                                 encoding='utf-8',
                                 ) as proc:
                    for line in proc.stderr:
                        pass

            except (OSError, FileNotFoundError) as e:
                GLib.idle_add(self.update_ui_on_error, str(e))
                return

            fraction = (i + 1) / len(self.files)
            GLib.idle_add(self.progress_bar.set_fraction, fraction)

        GLib.idle_add(self.close)

    def update_ui_on_error(self, error_message):
        self.label.set_text(_("Error: {0}").format(error_message))

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
        
        excluded_format = None
        if len(mime_types) == 1:
            mime_type = mime_types.pop()
            if mime_type == 'image/jpeg':
                excluded_format = 'JPG'
            elif mime_type == 'image/png':
                excluded_format = 'PNG'
            elif mime_type == 'image/bmp':
                excluded_format = 'BMP'
            elif mime_type == 'image/tiff':
                excluded_format = 'TIFF'
            elif mime_type == 'image/webp':
                excluded_format = 'WEBP'

        formats = ['JPG', 'PNG', 'BMP', 'TIFF', 'WEBP']
        
        for format in formats:
            if format != excluded_format:
                self.add_submenu_item(submenu, format, files)

        return [item]

    def add_submenu_item(self, submenu, format, files):
        item = Nautilus.MenuItem(
            name=f'ImageConverterExtension::Convert::{format}',
            label=format,
            tip=_('Convert to {0}').format(format)
        )
        item.connect('activate', self.run_converter, files, format.lower())
        submenu.append_item(item)

    def run_converter(self, menu, files, format):
        file_paths = [file.get_location().get_path() for file in files]
        subprocess.Popen([sys.executable, __file__, format] + file_paths)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        format = sys.argv[1]
        files = sys.argv[2:]
        app = Gtk.Application(application_id="org.gnome.nautilus.image-converter")
        def on_activate(app):
            win = ImageConverterWindow(files, format, app)
            win.set_visible(True)
        app.connect('activate', on_activate)
        app.run(None)