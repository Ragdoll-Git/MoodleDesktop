"""
Silent full-screen capture for GNOME/Wayland via the XDG ScreenCast portal.

Unlike the Screenshot portal (which makes GNOME Shell flash the screen and play
a shutter sound), ScreenCast grabs frames from a PipeWire stream with no visual
or audio feedback. A single session is opened once (asking the user to share the
screen a single time, remembered via restore_token) and reused for every frame.
"""

import os

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

from PIL import Image

Gst.init(None)

_PORTAL_BUS = 'org.freedesktop.portal.Desktop'
_PORTAL_PATH = '/org/freedesktop/portal/desktop'
_SCREENCAST_IFACE = 'org.freedesktop.portal.ScreenCast'
_REQUEST_IFACE = 'org.freedesktop.portal.Request'

# SelectSources option values
_SOURCE_TYPE_MONITOR = 1
_CURSOR_MODE_HIDDEN = 1
_PERSIST_MODE_PERSISTENT = 2


class ScreenCastError(Exception):
    pass


class ScreenCastSession:
    def __init__(self, restore_token=None, on_token=None):
        """
        :param restore_token: previously saved token to skip the permission dialog
        :param on_token: callback(str) invoked with a fresh restore_token to persist
        """
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.restore_token = restore_token
        self.on_token = on_token
        self.session_handle = None
        self.node_id = None
        self._counter = 0

        unique = self.bus.get_unique_name()  # e.g. ":1.234"
        self._sender_token = unique[1:].replace('.', '_')

        self._ctx = GLib.MainContext.new()
        self._ctx.push_thread_default()  # signal_subscribe dispatches here
        try:
            self._open_session()
        except Exception:
            self.close()
            raise
        finally:
            self._ctx.pop_thread_default()

    # -- low-level portal helpers -------------------------------------------

    def _token(self, prefix):
        self._counter += 1
        return f"{prefix}{self._counter}"

    def _request_path(self, handle_token):
        return f"{_PORTAL_PATH}/request/{self._sender_token}/{handle_token}"

    def _call_request(self, method, body_variant, handle_token):
        """Invoke a portal method that returns a Request, block for its Response.

        Returns the results dict (str -> GLib.Variant). Raises on failure.
        """
        request_path = self._request_path(handle_token)
        loop = GLib.MainLoop(self._ctx)
        outcome = {}

        def on_response(conn, sender, path, iface, signal, params):
            code, results = params.unpack()
            outcome['code'] = code
            outcome['results'] = results
            loop.quit()

        sub_id = self.bus.signal_subscribe(
            _PORTAL_BUS, _REQUEST_IFACE, 'Response', request_path, None,
            Gio.DBusSignalFlags.NONE, on_response)

        def on_timeout():
            outcome.setdefault('code', -1)
            loop.quit()
            return False

        timeout_src = GLib.timeout_source_new_seconds(60)
        timeout_src.set_callback(lambda *_: on_timeout())
        timeout_src.attach(self._ctx)
        try:
            self.bus.call_sync(
                _PORTAL_BUS, _PORTAL_PATH, _SCREENCAST_IFACE, method,
                body_variant, GLib.VariantType('(o)'),
                Gio.DBusCallFlags.NONE, -1, None)
            loop.run()
        finally:
            self.bus.signal_unsubscribe(sub_id)
            timeout_src.destroy()

        if outcome.get('code') != 0:
            raise ScreenCastError(
                f"{method} failed or was cancelled (code {outcome.get('code')})")
        return outcome.get('results', {})

    # -- session lifecycle ---------------------------------------------------

    def _open_session(self):
        # 1. CreateSession
        ht = self._token('cs')
        sht = self._token('sess')
        opts = {
            'handle_token': GLib.Variant('s', ht),
            'session_handle_token': GLib.Variant('s', sht),
        }
        results = self._call_request(
            'CreateSession', GLib.Variant('(a{sv})', (opts,)), ht)
        self.session_handle = results['session_handle']

        # 2. SelectSources
        ht = self._token('ss')
        opts = {
            'handle_token': GLib.Variant('s', ht),
            'types': GLib.Variant('u', _SOURCE_TYPE_MONITOR),
            'multiple': GLib.Variant('b', False),
            'cursor_mode': GLib.Variant('u', _CURSOR_MODE_HIDDEN),
            'persist_mode': GLib.Variant('u', _PERSIST_MODE_PERSISTENT),
        }
        if self.restore_token:
            opts['restore_token'] = GLib.Variant('s', self.restore_token)
        self._call_request(
            'SelectSources',
            GLib.Variant('(oa{sv})', (self.session_handle, opts)), ht)

        # 3. Start (shows the share dialog unless restore_token is accepted)
        ht = self._token('st')
        opts = {'handle_token': GLib.Variant('s', ht)}
        results = self._call_request(
            'Start',
            GLib.Variant('(osa{sv})', (self.session_handle, '', opts)), ht)

        streams = results.get('streams') or []
        if not streams:
            raise ScreenCastError("ScreenCast returned no streams")
        self.node_id = streams[0][0]

        new_token = results.get('restore_token')
        if new_token and self.on_token:
            self.on_token(new_token)

    # -- frame capture -------------------------------------------------------

    def _open_pipewire_fd(self):
        result, fd_list = self.bus.call_with_unix_fd_list_sync(
            _PORTAL_BUS, _PORTAL_PATH, _SCREENCAST_IFACE, 'OpenPipeWireRemote',
            GLib.Variant('(oa{sv})', (self.session_handle, {})),
            GLib.VariantType('(h)'), Gio.DBusCallFlags.NONE, -1, None, None)
        idx = result.unpack()[0]
        return fd_list.get(idx)

    def capture(self) -> Image.Image:
        """Grab a single frame and return it as a PIL Image."""
        fd = self._open_pipewire_fd()
        pipeline = Gst.parse_launch(
            f"pipewiresrc fd={fd} path={self.node_id} num-buffers=1 ! "
            f"videoconvert ! video/x-raw,format=RGBx ! "
            f"appsink name=sink max-buffers=1 drop=false sync=false")
        sink = pipeline.get_by_name('sink')
        pipeline.set_state(Gst.State.PLAYING)
        try:
            # pipewiresrc dups the fd; close our copy once the pipeline owns it.
            sample = sink.emit('try-pull-sample', 10 * Gst.SECOND)
            if sample is None:
                raise ScreenCastError("No frame received from PipeWire stream")

            caps = sample.get_caps().get_structure(0)
            width = caps.get_value('width')
            height = caps.get_value('height')

            buf = sample.get_buffer()
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if not ok:
                raise ScreenCastError("Failed to map frame buffer")
            try:
                data = bytes(mapinfo.data)
            finally:
                buf.unmap(mapinfo)

            # RGBx: 4 bytes/pixel, row stride = width*4 (4-byte aligned).
            return Image.frombytes('RGB', (width, height), data, 'raw', 'RGBX', 0, 1)
        finally:
            pipeline.set_state(Gst.State.NULL)
            try:
                os.close(fd)
            except OSError:
                pass

    def close(self):
        if self.session_handle:
            try:
                self.bus.call_sync(
                    _PORTAL_BUS, self.session_handle,
                    'org.freedesktop.portal.Session', 'Close',
                    None, None, Gio.DBusCallFlags.NONE, -1, None)
            except GLib.Error:
                pass
            self.session_handle = None

