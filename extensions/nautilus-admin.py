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

    def get_file_items(self, window, files):
        if not files:
            return

        if len(files) > 1:
            return

        file = files[0]
        if file.get_uri_scheme() not in ('file',):
            return

        if file.is_directory():
            return
        
        if not file.get_mime_type().startswith('text/'):
            return

        if file.get_location().get_path() == '/':
            return

        editor_path = self._get_text_editor()
        if not editor_path:
            return

        item = Nautilus.MenuItem(name='NautilusAdmin::EditAdmin',
                                 label=_(u'_Edit as Administrator'),
                                 tip=_(u'Edits the current file as an administrator'),
                                 icon='nautilus-admin')
        item.connect('activate', self._gedit_run, file, editor_path)

        return [item]

    def get_background_items(self, window, folder):
        if folder.get_uri_scheme() not in ('file',):
            return

        if folder.get_location().get_path() == '/':
            return

        item = Nautilus.MenuItem(name='NautilusAdmin::OpenAdmin',
                                 label=_(u'Open as _Administrator'),
                                 tip=_(u'Opens the current folder as an administrator'),
                                 icon='nautilus-admin')
        item.connect('activate', self._nautilus_run, folder)

        return [item]

    def _nautilus_run(self, menu, file):
        uri = file.get_uri()
        admin_uri = uri.replace("file://", "admin://")
        subprocess.Popen([NAUTILUS_PATH, admin_uri])

    def _gedit_run(self, menu, file, editor_path):
        uri = file.get_uri()
        admin_uri = uri.replace("file://", "admin://")
        subprocess.Popen([editor_path, admin_uri])
