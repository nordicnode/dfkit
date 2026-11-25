"""Minimal DFHack RPC client for Dwarf Fortress 0.47.05 / DFHack 0.47.05-r5.

Implements the wire protocol documented in DFHack's Remote.html:
  handshake: b"DFHack?\\n" + int32 version, expect b"DFHack!\\n" + int32
  request:   header(int16 id, int16 pad, int32 size) + protobuf payload
  reply:     header followed by text notifications, then result or failure

Only the standard library, the protobuf runtime and the generated stubs in
this directory are required.
"""
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import CoreProtocol_pb2 as core  # noqa: E402
import RemoteFortressReader_pb2 as rfr  # noqa: E402

RPC_REPLY_RESULT = -1
RPC_REPLY_FAIL = -2
RPC_REPLY_TEXT = -3

MAGIC_REQUEST = b"DFHack?\n"
MAGIC_REPLY = b"DFHack!\n"
PROTOCOL_VERSION = 1

DEFAULT_PORT = 5001

# method name -> (input message, output message)
# Input/output names are fully qualified protobuf message names.
CORPUS = {
    "GetVersionInfo": ("dfproto.EmptyMessage", "RemoteFortressReader.VersionInfo"),
    "GetPauseState": ("dfproto.EmptyMessage", "RemoteFortressReader.SingleBool"),
    "SetPauseState": ("RemoteFortressReader.SingleBool", "dfproto.EmptyMessage"),
    "GetMapInfo": ("dfproto.EmptyMessage", "RemoteFortressReader.MapInfo"),
    "GetUnitList": ("dfproto.EmptyMessage", "RemoteFortressReader.UnitList"),
    "GetUnitListInside": ("RemoteFortressReader.BlockRequest", "RemoteFortressReader.UnitList"),
    "GetViewInfo": ("dfproto.EmptyMessage", "RemoteFortressReader.ViewInfo"),
    "GetBlockList": ("RemoteFortressReader.BlockRequest", "RemoteFortressReader.BlockList"),
    "GetTiletypeList": ("dfproto.EmptyMessage", "RemoteFortressReader.TiletypeList"),
    "GetItemList": ("dfproto.EmptyMessage", "RemoteFortressReader.MaterialList"),
    "GetBuildingDefList": ("dfproto.EmptyMessage", "RemoteFortressReader.BuildingList"),
    "GetReports": ("dfproto.EmptyMessage", "RemoteFortressReader.Status"),
    "GetCreatureRaws": ("dfproto.EmptyMessage", "RemoteFortressReader.CreatureRawList"),
    "CopyScreen": ("dfproto.EmptyMessage", "RemoteFortressReader.ScreenCapture"),
    "SendDigCommand": ("RemoteFortressReader.DigCommand", "dfproto.EmptyMessage"),
    "PassKeyboardEvent": ("RemoteFortressReader.KeyboardEvent", "dfproto.EmptyMessage"),
    "CheckHashes": ("dfproto.EmptyMessage", "dfproto.EmptyMessage"),
    "ResetMapHashes": ("dfproto.EmptyMessage", "dfproto.EmptyMessage"),
    "GetWorldMap": ("dfproto.EmptyMessage", "RemoteFortressReader.WorldMap"),
}

OUTPUT_TYPES = {name: out for name, (_, out) in CORPUS.items()}


def _decode(value):
    """DFHack strings are bytes in DF's CP437 encoding; prefer UTF-8 if valid."""
    if isinstance(value, str):
        return value
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("cp437", "replace")


class RPCError(RuntimeError):
    """The server rejected a request or the connection broke."""

    def __init__(self, message, code=None, text=""):
        super().__init__(message)
        self.code = code
        self.text = text


class DFHackClient:
    def __init__(self, port=None, host="127.0.0.1", timeout=20.0):
        self.host = host
        self.port = int(port or os.environ.get("DFHACK_PORT", DEFAULT_PORT))
        self.timeout = timeout
        self.sock = None
        self._bound = {}

    # -- connection -----------------------------------------------------
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.sendall(MAGIC_REQUEST + struct.pack("<i", PROTOCOL_VERSION))
        reply = self._recv_exact(12)
        if reply[:8] != MAGIC_REPLY:
            raise RPCError("bad handshake magic from DFHack: %r" % reply[:8])
        version = struct.unpack("<i", reply[8:])[0]
        if version != PROTOCOL_VERSION:
            raise RPCError("unsupported DFHack protocol version %d" % version)
        return self

    def close(self):
        if self.sock is None:
            return
        try:
            self.sock.sendall(struct.pack("<hhi", -4, 0, 0))  # RPC_REQUEST_QUIT
        except OSError:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- low level ------------------------------------------------------
    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RPCError("DFHack closed the connection")
            buf.extend(chunk)
        return bytes(buf)

    def _request(self, method_id, message):
        if self.sock is None:
            self.connect()
        payload = message.SerializeToString()
        self.sock.sendall(struct.pack("<hhi", method_id, 0, len(payload)) + payload)
        texts = []
        while True:
            header = self._recv_exact(8)
            reply_id, _, size = struct.unpack("<hhi", header)
            if reply_id == RPC_REPLY_TEXT:
                body = self._recv_exact(size) if size else b""
                note = core.CoreTextNotification.FromString(body)
                texts.append("".join(_decode(frag.text) for frag in note.fragments))
                continue
            if reply_id == RPC_REPLY_RESULT:
                body = self._recv_exact(size) if size else b""
                return body, "".join(texts)
            if reply_id == RPC_REPLY_FAIL:
                # the failure code is carried in the size field
                raise RPCError("DFHack call failed", code=size, text="".join(texts))
            raise RPCError("unexpected reply id %d" % reply_id)

    # -- RPC methods ----------------------------------------------------
    def bind(self, method, plugin="RemoteFortressReader"):
        key = (plugin, method)
        if key in self._bound:
            return self._bound[key]
        if method not in CORPUS:
            raise RPCError("unknown method %r" % method)
        in_name, out_name = CORPUS[method]
        request = core.CoreBindRequest(method=method, input_msg=in_name, output_msg=out_name)
        if plugin:
            request.plugin = plugin
        body, _ = self._request(0, request)  # BindMethod is id 0
        reply = core.CoreBindReply.FromString(body)
        self._bound[key] = reply.assigned_id
        return reply.assigned_id

    def call(self, method, message, plugin="RemoteFortressReader"):
        # RunCommand has the hardcoded id 1 and is not bound through BindMethod.
        method_id = 1 if method == "RunCommand" else self.bind(method, plugin=plugin)
        body, text = self._request(method_id, message)
        out_type = OUTPUT_TYPES.get(method, "dfproto.EmptyMessage")
        cls = _resolve_message(out_type)
        if cls is None or out_type == "dfproto.EmptyMessage":
            return None, text
        return cls.FromString(body), text

    def simple(self, method, plugin="RemoteFortressReader"):
        return self.call(method, core.EmptyMessage(), plugin=plugin)[0]

    # -- convenience ----------------------------------------------------
    def version(self):
        return self.simple("GetVersionInfo")

    def paused(self):
        return self.simple("GetPauseState").Value

    def set_paused(self, paused):
        msg = rfr.SingleBool()
        msg.Value = bool(paused)
        self.call("SetPauseState", msg)

    def units(self):
        return list(self.simple("GetUnitList").creature_list)

    def units_inside(self, x0, x1, y0, y1, z0, z1, blocks_needed=1):
        req = rfr.BlockRequest()
        req.min_x, req.max_x = x0, x1
        req.min_y, req.max_y = y0, y1
        req.min_z, req.max_z = z0, z1
        req.blocks_needed = blocks_needed
        return list(self.call("GetUnitListInside", req)[0].creature_list)

    def map_info(self):
        return self.simple("GetMapInfo")

    def blocks(self, x0, x1, y0, y1, z0, z1, blocks_needed=1):
        req = rfr.BlockRequest()
        req.min_x, req.max_x = x0, x1
        req.min_y, req.max_y = y0, y1
        req.min_z, req.max_z = z0, z1
        req.blocks_needed = blocks_needed
        return self.call("GetBlockList", req)[0]

    def items(self):
        return self.simple("GetItemList")

    def reports(self):
        return list(self.simple("GetReports").reports)

    def screen(self):
        return self.simple("CopyScreen")

    def dig(self, locations, designation=None):
        """locations: iterable of (x, y, z). designation: TileDigDesignation value."""
        msg = rfr.DigCommand()
        if designation is not None:
            msg.designation = designation
        for x, y, z in locations:
            c = msg.locations.add()
            c.x, c.y, c.z = int(x), int(y), int(z)
        self.call("SendDigCommand", msg)

    def run_command(self, command, *args, plugin=None):
        """Run a DFHack console command. Returns (ok, text)."""
        req = core.CoreRunCommandRequest(command=command)
        req.arguments.extend(str(a) for a in args)
        try:
            _, text = self.call("RunCommand", req, plugin=plugin or "Core")
            return True, text
        except RPCError as exc:
            return False, (exc.text or str(exc))

    def send_keys(self, syms, delay=0.05):
        """Push SDL key down/up events into the game (syms are SDL 1.2 keycodes)."""
        import time
        for sym in syms:
            for etype, state in ((2, 1), (3, 0)):  # SDL_KEYDOWN, SDL_KEYUP
                msg = rfr.KeyboardEvent()
                msg.type = etype
                msg.state = state
                msg.sym = sym
                msg.scancode = 0
                msg.unicode = sym if 32 <= sym < 127 else 0
                msg.mod = 0
                self.call("PassKeyboardEvent", msg)
            time.sleep(delay)

    def run_lua(self, code):
        """Evaluate Lua in the DFHack interpreter; returns (ok, text)."""
        return self.run_command("lua", code)


_MESSAGE_CACHE = {}


def _resolve_message(name):
    """Map a fully qualified proto name to a generated message class."""
    if name in _MESSAGE_CACHE:
        return _MESSAGE_CACHE[name]
    package, _, msg = name.rpartition(".")
    module = {"dfproto": core, "RemoteFortressReader": rfr}.get(package)
    cls = getattr(module, msg, None) if module else None
    _MESSAGE_CACHE[name] = cls
    return cls


def connect(port=None, host="127.0.0.1", timeout=20.0):
    return DFHackClient(port=port, host=host, timeout=timeout).connect()
