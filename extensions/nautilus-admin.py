import os
import subprocess
from gi.repository import Nautilus, GObject
from common import setup_localisation

_ = setup_localisation()

ROOT_UID = 0
NAUTILUS_PATH = "/usr/bin/nautilus"
TEXT_EDITOR_PATHS = ["/usr/bin/gnome-text-editor", "/usr/bin/gedit"]


class NautilusAdmin(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        pass

    def _is_root(self):
        """
        Checks if the script is running with root privileges.
        Tries checking the USER environment variable first, then falls back to geteuid.
        """
        if os.environ.get('USER') == 'root':
            return True
        try:
            if os.geteuid() == ROOT_UID:
                return True
        except AttributeError:
            pass
        return False

    def _get_text_editor(self):
        for editor in TEXT_EDITOR_PATHS:
            if os.path.exists(editor):
                return editor
        return None

    def get_file_items(self, *args):
        files = args[-1]
        if self._is_root() or len(files) != 1:
            return

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
            return

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

    def _nautilus_run(self, menu, file):
        uri = file.get_uri()
        admin_uri = uri.replace("file://", "admin://")
        subprocess.Popen([NAUTILUS_PATH, admin_uri])

    def _gedit_run(self, menu, file, editor_path):
        uri = file.get_uri()
        admin_uri = uri.replace("file://", "admin://")
        subprocess.Popen([editor_path, admin_uri])
