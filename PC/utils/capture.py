import os
import sys
import base64
import io
import time

from PIL import Image

_ON_WAYLAND = sys.platform == 'linux' and os.environ.get('XDG_SESSION_TYPE') == 'wayland'

# Silent capture via ScreenCast. The session is opened per capture and closed right
# after, so GNOME's "screen sharing" indicator only shows for a moment. The permission
# (restore token) is kept so the share dialog appears only once.
_sc_state = None  # {'token': str|None, 'on_token': callable|None}


def _new_session():
    from utils.screencast import ScreenCastSession

    def on_token(t):
        _sc_state['token'] = t
        if _sc_state['on_token']:
            _sc_state['on_token'](t)

    return ScreenCastSession(restore_token=_sc_state['token'], on_token=on_token)


def init_screencast(restore_token=None, on_token=None):
    """Enable silent capture. Returns True on success.

    Opens a session once (main thread, before the Qt loop) so the one-time
    'share screen' dialog shows now if there is no saved token, then closes it.
    """
    global _sc_state
    if not _ON_WAYLAND:
        return False
    _sc_state = {'token': restore_token, 'on_token': on_token}
    try:
        _new_session().close()
        return True
    except Exception as e:
        print(f"[capture] ScreenCast no disponible, usando portal con flash: {e}")
        _sc_state = None
        return False


def _capture_wayland_portal() -> bytes:
    """Capture full screen via XDG Desktop Portal (works on GNOME/KDE Wayland)."""
    from jeepney import DBusAddress, new_method_call, MessageType, HeaderFields
    from jeepney.io.blocking import open_dbus_connection

    conn = open_dbus_connection(bus='SESSION')

    portal = DBusAddress(
        '/org/freedesktop/portal/desktop',
        bus_name='org.freedesktop.portal.Desktop',
        interface='org.freedesktop.portal.Screenshot'
    )

    msg = new_method_call(portal, 'Screenshot', 'sa{sv}', ('', {'flash': ('b', False), 'interactive': ('b', False)}))
    reply = conn.send_and_get_reply(msg)
    request_path = reply.body[0]

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        incoming = conn.receive(timeout=5)
        if (incoming.header.message_type == MessageType.signal and
                incoming.header.fields.get(HeaderFields.path) == request_path and
                incoming.header.fields.get(HeaderFields.member) == 'Response'):
            response, results = incoming.body
            if response != 0:
                raise RuntimeError(f"Portal screenshot cancelled or failed (code {response})")
            raw_uri = results['uri']
            # GVariant tuple: ('s', 'file:///...')
            uri = raw_uri[1] if isinstance(raw_uri, tuple) else raw_uri
            path = uri.removeprefix('file://')
            with open(path, 'rb') as f:
                return f.read()

    raise TimeoutError("XDG Screenshot portal did not respond in time")


def _capture_mss() -> bytes:
    """Capture via mss (X11 / XWayland)."""
    import mss
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def capture_screen_base64() -> str:
    if _sc_state is not None:
        try:
            session = _new_session()
            try:
                img = session.capture()
            finally:
                session.close()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode('utf-8')
        except Exception as e:
            print(f"[capture] ScreenCast falló, usando portal: {e}")

    if _ON_WAYLAND:
        raw = _capture_wayland_portal()
    else:
        raw = _capture_mss()
    return base64.b64encode(raw).decode('utf-8')


def get_theme_hint_from_image(img: Image.Image) -> str:
    """Returns 'light' or 'dark' from an already-captured PIL Image."""
    w, h = img.size
    bottom_strip = img.crop((0, int(h * 0.8), w, h)).resize((1, 1))
    r, g, b = bottom_strip.getpixel((0, 0))[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return 'light' if luminance > 127.5 else 'dark'


def get_screen_theme_hint() -> str:
    """Returns 'light' or 'dark' based on the average color of the bottom 20% of the screen."""
    if _ON_WAYLAND:
        try:
            raw = _capture_wayland_portal()
            img = Image.open(io.BytesIO(raw))
        except Exception:
            return 'dark'
    else:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            bottom_rect = {
                "top": monitor["top"] + int(monitor["height"] * 0.8),
                "left": monitor["left"],
                "width": monitor["width"],
                "height": int(monitor["height"] * 0.2)
            }
            sct_img = sct.grab(bottom_rect)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    return get_theme_hint_from_image(img)
