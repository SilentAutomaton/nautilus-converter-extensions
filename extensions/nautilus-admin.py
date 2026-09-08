import os
import subprocess
from gi.repository import Nautilus, GObject
from common import setup_localisation

_ = setup_localisation()

NAUTILUS_PATH = "/usr/bin/nautilus"
TEXT_EDITOR_PATHS = ["/usr/bin/gnome-text-editor", "/usr/bin/gedit"]


class NautilusAdmin(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def _is_root(self):
        return os.geteuid() == 0

    def _get_text_editor(self):
        for editor in TEXT_EDITOR_PATHS:
            if os.path.exists(editor):
                return editor
        return None

    def get_file_items(self, *args):
        files = args[-1]
        if self._is_root() or len(files) != 1:
            return []

        file = files[0]
        items = []

        if file.get_uri_scheme() == "file":
            if file.is_directory():
                if os.path.exists(NAUTILUS_PATH):
                    items.append(self._create_nautilus_item(file))
            else:  # It's a file
                is_text = file.get_mime_type().startswith('text/')
                filename = file.get_name()
                has_no_extension = '.' not in filename or filename.rfind('.') == 0
                if is_text or has_no_extension:
                    editor = self._get_text_editor()
                    if editor:
                        items.append(self._create_gedit_item(file, editor))

        return items

    def get_background_items(self, *args):
        file = args[-1]
        if self._is_root():
            return []

        items = []
        if file.is_directory() and file.get_uri_scheme() == "file":
            if os.path.exists(NAUTILUS_PATH):
                items.append(self._create_nautilus_item(file))

        return items

    def _create_nautilus_item(self, file):
        item = Nautilus.MenuItem(
            name="NautilusAdmin::Nautilus",
            label=_("Open as Administrator"),
            tip=_("Open this folder with root privileges"),
        )
        item.connect("activate", self._nautilus_run, file)
        return item

    def _create_gedit_item(self, file, editor_path):
        item = Nautilus.MenuItem(
            name="NautilusAdmin::Gedit",
            label=_("Edit as Administrator"),
            tip=_("Open this file in the text editor with root privileges"),
        )
        item.connect("activate", self._gedit_run, file, editor_path)
        return item

    def _admin_uri(self, file):
        uri = file.get_uri()
        return "admin://" + uri[len("file://"):] if uri.startswith("file://") else uri

    def _nautilus_run(self, menu, file):
        subprocess.Popen([NAUTILUS_PATH, self._admin_uri(file)])

    def _gedit_run(self, menu, file, editor_path):
        subprocess.Popen([editor_path, self._admin_uri(file)])
