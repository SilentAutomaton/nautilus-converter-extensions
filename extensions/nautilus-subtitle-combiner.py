from gi.repository import Nautilus, GObject, Gtk, GLib
import os
from common import (
    setup_localisation,
    get_duration,
    FFMPEG_CMD,
    FFMPEG_DEFAULT_ARGS,
    BaseConverterWindow,
)

_ = setup_localisation()

SUBTITLE_EXTENSIONS = frozenset([
    '.srt', '.ass', '.ssa', '.vtt', '.sub', '.smi', '.idx', '.sup'
])

# Subtitle formats that can be transcoded by ffmpeg (text-based).
# Bitmap formats (.idx, .sup) can only be copied into MKV, not converted.
TEXT_SUBTITLE_EXTENSIONS = frozenset([
    '.srt', '.ass', '.ssa', '.vtt', '.sub', '.smi'
])

# Video containers that support embedding subtitle streams via ffmpeg.
# AVI, MPEG-PS and most others do not support subtitle tracks at all.
SUBTITLE_CAPABLE_MIME_TYPES = frozenset([
    'video/mp4', 'video/x-m4v', 'video/quicktime', 'video/webm',
])


def is_subtitle_file(file):
    return os.path.splitext(file.get_name().lower())[1] in SUBTITLE_EXTENSIONS


def subtitle_combiner_pass(*args, **kwa):
    """
    Command builder for subtitle embedding pass.
    Output is always MKV — it supports all subtitle formats natively.
    """
    pass1 = FFMPEG_CMD + FFMPEG_DEFAULT_ARGS.split()
    pass1.extend(['-i', kwa["video_file"]])
    for sub_file in kwa["subtitle_files"]:
        pass1.extend(['-i', sub_file])

    pass1.extend(['-map', '0'])
    for i in range(len(kwa["subtitle_files"])):
        pass1.extend(['-map', f'{i + 1}'])

    pass1.extend(['-c', 'copy'])
    pass1.append(kwa["destination"])

    count1 = _("Embedding {0} subtitle track(s) into \"{1}\"...").format(
        len(kwa["subtitle_files"]), os.path.basename(kwa["video_file"])
    )

    return {'pass1': pass1, 'count1': count1}


def subtitle_convert_and_embed_pass(*args, **kwa):
    """
    Command builder for converting text subtitles and embedding into the original container.
    Does not specify -c:s so ffmpeg auto-selects the subtitle codec for the output format
    (e.g. mov_text for MP4, webvtt for WebM).
    """
    pass1 = FFMPEG_CMD + FFMPEG_DEFAULT_ARGS.split()
    pass1.extend(['-i', kwa["video_file"]])
    for sub_file in kwa["subtitle_files"]:
        pass1.extend(['-i', sub_file])

    pass1.extend(['-map', '0'])
    for i in range(len(kwa["subtitle_files"])):
        pass1.extend(['-map', f'{i + 1}'])

    pass1.extend(['-c:v', 'copy', '-c:a', 'copy'])
    pass1.append(kwa["destination"])

    count1 = _("Converting subtitles and embedding into \"{0}\"...").format(
        os.path.basename(kwa["video_file"])
    )

    return {'pass1': pass1, 'count1': count1}


def subtitle_remux_to_mkv_pass(*args, **kwa):
    """
    Command builder for remuxing non-MKV video to MKV with subtitle embedding.
    Uses -fflags +genpts to fix missing PTS in containers like AVI that store
    only DTS, which causes ffmpeg to fail during remux with -c copy.
    """
    pass1 = FFMPEG_CMD + FFMPEG_DEFAULT_ARGS.split()
    pass1.extend(['-fflags', '+genpts'])
    pass1.extend(['-i', kwa["video_file"]])
    for sub_file in kwa["subtitle_files"]:
        pass1.extend(['-i', sub_file])

    pass1.extend(['-map', '0'])
    for i in range(len(kwa["subtitle_files"])):
        pass1.extend(['-map', f'{i + 1}'])

    pass1.extend(['-c', 'copy'])
    pass1.append(kwa["destination"])

    count1 = _("Converting to MKV with {0} subtitle track(s)...").format(
        len(kwa["subtitle_files"])
    )

    return {'pass1': pass1, 'count1': count1}


class SubtitleCombinerWindow(BaseConverterWindow):
    def __init__(self, files, mode='embed'):
        self._mode = mode

        if mode == 'convert_subs':
            title = _("Converting and Embedding Subtitles")
        elif mode == 'to_mkv':
            title = _("Converting to MKV and Adding Subtitles")
        else:
            title = _("Embedding Subtitles")

        super().__init__(
            title=title,
            files=files,
            default_size=(500, 250),
            show_progress_details=True,
        )

        self._setup_progress_ui()

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_handler_id = self.cancel_button.connect("clicked", self.on_cancel_clicked)
        self.vbox.append(self.cancel_button)

        self._start_conversion()

    def on_cancel_clicked(self, widget):
        if self.thread and self.thread.is_alive():
            self.thread.stop()
        self.cancel_button.set_sensitive(False)

    def _start_conversion(self):
        video_file = None
        subtitle_files = []

        for file in self.files:
            path = file.get_location().get_path()
            if file.get_mime_type().startswith('video/'):
                video_file = path
            elif is_subtitle_file(file):
                subtitle_files.append(path)

        if not video_file or not subtitle_files:
            self.label_file_count.set_text(
                _("Error: Select one video and at least one subtitle file.")
            )
            GLib.timeout_add(3000, self.close)
            return

        duration = get_duration(video_file)
        base = os.path.splitext(video_file)[0]

        if self._mode == 'convert_subs':
            ext = os.path.splitext(video_file)[1]
            output_path = f"{base}_with_subs{ext}"
            cmd_builder = subtitle_convert_and_embed_pass
        elif self._mode == 'to_mkv':
            output_path = f"{base}_with_subs.mkv"
            cmd_builder = subtitle_remux_to_mkv_pass
        else:  # 'embed'
            output_path = f"{base}_with_subs.mkv"
            cmd_builder = subtitle_combiner_pass

        kwargs = {
            'video_file': video_file,
            'subtitle_files': subtitle_files,
            'destination': output_path,
            'duration': duration * 1000,
            'source': video_file,
        }

        self._start_ffmpeg([kwargs], cmd_builder=cmd_builder)

    def end_conversion(self, filedone):
        self.cancel_button.set_label(_("Close"))
        self.cancel_button.set_sensitive(True)
        if self.cancel_handler_id > 0:
            self.cancel_button.disconnect(self.cancel_handler_id)
            self.cancel_handler_id = 0
        self.cancel_button.connect("clicked", lambda w: self.close())


class SubtitleCombinerExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        GObject.GObject.__init__(self)

    def get_file_items(self, files):
        if len(files) < 2:
            return []

        video_files = [f for f in files if f.get_mime_type().startswith('video/')]
        sub_files = [f for f in files if is_subtitle_file(f)]

        if len(video_files) != 1 or not sub_files:
            return []

        if len(video_files) + len(sub_files) != len(files):
            return []

        video = video_files[0]
        is_mkv = video.get_mime_type() == 'video/x-matroska'

        if is_mkv:
            item = Nautilus.MenuItem(
                name='SubtitleCombinerExtension::Embed',
                label=_('Embed Subtitles'),
                tip=_('Embed subtitle file(s) into the MKV video as tracks')
            )
            item.connect('activate', self.show_window, files, 'embed')
            return [item]

        # Non-MKV video: offer one or two options depending on subtitle types
        items = []

        all_text_subs = all(
            os.path.splitext(f.get_name().lower())[1] in TEXT_SUBTITLE_EXTENSIONS
            for f in sub_files
        )

        if all_text_subs and video.get_mime_type() in SUBTITLE_CAPABLE_MIME_TYPES:
            item = Nautilus.MenuItem(
                name='SubtitleCombinerExtension::ConvertSubs',
                label=_('Convert Subtitles and Add to Video'),
                tip=_('Convert subtitles to container format and embed in the video file')
            )
            item.connect('activate', self.show_window, files, 'convert_subs')
            items.append(item)

        item = Nautilus.MenuItem(
            name='SubtitleCombinerExtension::ToMkv',
            label=_('Convert to MKV and Add Subtitles'),
            tip=_('Remux video to MKV format and embed subtitle file(s) as tracks')
        )
        item.connect('activate', self.show_window, files, 'to_mkv')
        items.append(item)

        return items

    def show_window(self, menu, files, mode):
        win = SubtitleCombinerWindow(files, mode=mode)
        win.set_visible(True)
