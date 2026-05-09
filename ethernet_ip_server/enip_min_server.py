import socket
import struct
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class TagDef:
    cip_type: int
    encode: Callable[[Any], bytes]
    decode: Callable[[bytes], Any]


def _enc_bool(v: Any) -> bytes:
    return b"\xff" if bool(v) else b"\x00"


def _dec_bool(b: bytes) -> bool:
    return b[:1] != b"\x00"


def _enc_int(v: Any) -> bytes:
    return struct.pack("<h", int(v))


def _dec_int(b: bytes) -> int:
    return struct.unpack("<h", b[:2])[0]


def _enc_dint(v: Any) -> bytes:
    return struct.pack("<i", int(v))


def _dec_dint(b: bytes) -> int:
    return struct.unpack("<i", b[:4])[0]


def _enc_real(v: Any) -> bytes:
    return struct.pack("<f", float(v))


def _dec_real(b: bytes) -> float:
    return struct.unpack("<f", b[:4])[0]


def _enc_lreal(v: Any) -> bytes:
    return struct.pack("<d", float(v))


def _enc_sint(v: Any) -> bytes:
    return struct.pack("b", int(v))


def _dec_sint(b: bytes) -> int:
    return struct.unpack("b", b[:1])[0]


def _enc_usint(v: Any) -> bytes:
    return struct.pack("B", int(v) & 0xFF)


def _dec_usint(b: bytes) -> int:
    return struct.unpack("B", b[:1])[0]


def _dec_lreal(b: bytes) -> float:
    return struct.unpack("<d", b[:8])[0]


TAG_TYPES: dict[str, TagDef] = {
    "BOOL": TagDef(0x00C1, _enc_bool, _dec_bool),
    "SINT": TagDef(0x00C2, _enc_sint, _dec_sint),
    "INT": TagDef(0x00C3, _enc_int, _dec_int),
    "DINT": TagDef(0x00C4, _enc_dint, _dec_dint),
    "USINT": TagDef(0x00C6, _enc_usint, _dec_usint),
    "REAL": TagDef(0x00CA, _enc_real, _dec_real),
    "LREAL": TagDef(0x00CB, _enc_lreal, _dec_lreal),
}


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def _pad_to_even(b: bytes) -> bytes:
    return b if (len(b) % 2) == 0 else b + b"\x00"


def _parse_symbolic_tag(path: bytes) -> str | None:
    # Expect at least: 0x91 <len> <name...> [pad]
    if len(path) < 2 or path[0] != 0x91:
        return None
    n = int(path[1])
    if len(path) < 2 + n:
        return None
    name = path[2 : 2 + n].decode("ascii", errors="ignore")
    return name


def _unwrap_unconnected_send(cip: bytes) -> bytes | None:
    # Based on cpppo.server.enip.parser.unconnected_send:
    # 0x52, EPATH (size in words inside EPATH), priority, timeout_ticks, length(UINT),
    # request[length], optional pad if length odd, then route_path.
    if len(cip) < 6 or cip[0] != 0x52:
        return None
    path_words = int(cip[1])
    path_len = path_words * 2
    off = 2 + path_len
    if len(cip) < off + 1 + 1 + 2:
        return None
    # priority = cip[off]
    off += 1
    # timeout_ticks = cip[off]
    off += 1
    msg_len = struct.unpack("<H", cip[off : off + 2])[0]
    off += 2
    if len(cip) < off + msg_len:
        return None
    msg = cip[off : off + msg_len]
    return bytes(msg)


def _cip_status_reply(service: int, general_status: int, addl: bytes = b"") -> bytes:
    # Reply: <service|0x80> <reserved> <general_status> <addl_count_words> <addl...>
    addl_words = (len(addl) + 1) // 2
    return bytes([service | 0x80, 0x00, general_status, addl_words]) + addl


def _cip_read_tag_reply(service: int, tag_type: int, data: bytes) -> bytes:
    # <service|0x80> 0x00 <sts> <addl_words> <type UINT> <data...>
    header = bytes([service | 0x80, 0x00, 0x00, 0x00]) + struct.pack("<H", int(tag_type))
    return header + data


def _cip_write_tag_reply(service: int) -> bytes:
    return _cip_status_reply(service, 0x00)


def _enip_header(command: int, length: int, session: int, status: int, sender_ctx: bytes, options: int) -> bytes:
    return struct.pack("<HHII8sI", command, length, session, status, sender_ctx, options)


def _cpf_item(type_id: int, payload: bytes) -> bytes:
    return struct.pack("<HH", type_id, len(payload)) + payload


def _build_sendrrdata_response(session: int, sender_ctx: bytes, cpf_payload: bytes, status: int = 0) -> bytes:
    # Command 0x006F, payload is interface(4)+timeout(2)+count(2)+items...
    cmd = 0x006F
    hdr = _enip_header(cmd, len(cpf_payload), session, status, sender_ctx, 0)
    return hdr + cpf_payload


class EnipTagServer:
    """
    Minimal EtherNet/IP explicit-message server for cpppo client.parse_operations() style Tag Read/Write.
    Supports:
    - RegisterSession (0x0065)
    - UnregisterSession (0x0066)
    - SendRRData (0x006F) with CPF item[1] type 0x00B2 carrying raw CIP service:
        - Read Tag (0x4C)
        - Write Tag (0x4D)
    """

    def __init__(self, host: str, port: int, tags: dict[str, tuple[str, Any]], lock: Optional[threading.Lock] = None):
        self.host = host
        self.port = port
        self.tags = tags  # name -> (TYPE_STR, value)
        self.lock = lock or threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.debug = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(20)
            s.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    conn, _addr = s.accept()
                except TimeoutError:
                    continue
                except OSError:
                    continue
                if self.debug:
                    try:
                        print("ACCEPT", _addr)
                    except Exception:
                        pass
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        session = 0
        try:
            with conn:
                while not self._stop.is_set():
                    hdr = _recv_exact(conn, 24)
                    command, length, sess, status, sender_ctx, options = struct.unpack("<HHII8sI", hdr)
                    payload = _recv_exact(conn, length) if length else b""
                    if self.debug:
                        print(
                            "ENIP_RX",
                            f"cmd=0x{command:04x}",
                            f"len={length}",
                            f"sess=0x{sess:08x}",
                            f"status=0x{status:08x}",
                            "payload_hex=" + payload[:200].hex(),
                        )

                    if command == 0x0065:  # RegisterSession
                        # Allocate a dummy session handle.
                        session = session or 0x12345678
                        reply_hdr = _enip_header(0x0065, 4, session, 0, sender_ctx, options)
                        # protocol_version(UINT) + options(UINT)
                        conn.sendall(reply_hdr + payload[:4].ljust(4, b"\x00"))
                        continue

                    if command == 0x0066:  # UnregisterSession
                        # No response required by spec; close.
                        return

                    if command != 0x006F:  # Only SendRRData supported here
                        # Unknown command -> status 0x08
                        reply = _enip_header(command, 0, sess, 0x08, sender_ctx, options)
                        conn.sendall(reply)
                        continue

                    # SendRRData payload:
                    # interface(4) timeout(2) cpf_count(2) then items...
                    if len(payload) < 8:
                        conn.sendall(_build_sendrrdata_response(sess, sender_ctx, payload=b"", status=0x08))
                        continue
                    interface_handle, timeout, item_count = struct.unpack("<IHH", payload[:8])
                    off = 8
                    items: list[tuple[int, bytes]] = []
                    for _ in range(item_count):
                        if off + 4 > len(payload):
                            break
                        type_id, item_len = struct.unpack("<HH", payload[off : off + 4])
                        off += 4
                        item = payload[off : off + item_len]
                        off += item_len
                        items.append((type_id, item))
                    if self.debug:
                        print(
                            "CPF_ITEMS",
                            [(hex(t), len(b), b[:80].hex()) for t, b in items],
                        )

                    # Expect item[1] 0x00B2 with raw CIP request bytes
                    cip_req = None
                    for type_id, item in items:
                        if type_id == 0x00B2:
                            cip_req = item
                            break

                    if not cip_req:
                        # Return CPF with empty item[1]
                        r_payload = struct.pack("<IHH", interface_handle, timeout, 2) + _cpf_item(0x0000, b"") + _cpf_item(0x00B2, b"")
                        conn.sendall(_build_sendrrdata_response(sess, sender_ctx, r_payload, status=0x08))
                        continue

                    # cpppo client 預設會把實際 CIP request 包在 Unconnected Send(0x52) 裡，
                    # 所以這裡要先解包，回覆則直接回「內層 CIP Reply bytes」即可。
                    if cip_req and cip_req[0] == 0x52:
                        inner = _unwrap_unconnected_send(cip_req)
                        cip_rsp = self._handle_cip(inner or b"")
                    else:
                        cip_rsp = self._handle_cip(cip_req)
                    r_payload = struct.pack("<IHH", interface_handle, timeout, 2) + _cpf_item(0x0000, b"") + _cpf_item(0x00B2, cip_rsp)
                    conn.sendall(_build_sendrrdata_response(sess, sender_ctx, r_payload, status=0))
        except Exception as e:
            if self.debug:
                try:
                    print("CONN_ERR", type(e).__name__, str(e))
                except Exception:
                    pass
            return

    def _handle_cip(self, cip: bytes) -> bytes:
        if not cip:
            return _cip_status_reply(0x00, 0x01)
        service = cip[0]
        if len(cip) < 2:
            return _cip_status_reply(service, 0x01)
        path_words = cip[1]
        path_len = int(path_words) * 2
        if len(cip) < 2 + path_len:
            return _cip_status_reply(service, 0x13)  # not enough data
        path = cip[2 : 2 + path_len]
        tag = _parse_symbolic_tag(path)
        if not tag:
            return _cip_status_reply(service, 0x04)  # path segment error
        data = cip[2 + path_len :]

        if service == 0x4C:  # Read Tag
            if len(data) < 2:
                return _cip_status_reply(service, 0x13)
            # elements = <UINT>
            # elements = struct.unpack("<H", data[:2])[0]
            with self.lock:
                entry = self.tags.get(tag)
                if not entry:
                    return _cip_status_reply(service, 0x05)  # path destination unknown
                type_str, value = entry
            td = TAG_TYPES.get(type_str.upper())
            if not td:
                return _cip_status_reply(service, 0x08)
            payload = td.encode(value)
            return _cip_read_tag_reply(service, td.cip_type, payload)

        if service == 0x4D:  # Write Tag
            if len(data) < 4:
                return _cip_status_reply(service, 0x13)
            tag_type = struct.unpack("<H", data[:2])[0]
            # elements = struct.unpack("<H", data[2:4])[0]
            payload = data[4:]
            # Find decoder by tag_type
            td = None
            for t in TAG_TYPES.values():
                if t.cip_type == tag_type:
                    td = t
                    break
            if not td:
                return _cip_status_reply(service, 0x08)
            with self.lock:
                if tag not in self.tags:
                    return _cip_status_reply(service, 0x05)
                type_str, _old = self.tags[tag]
                # Allow BOOL/INT/REAL/etc write if cip type matches
                self.tags[tag] = (type_str, td.decode(payload))
            return _cip_write_tag_reply(service)

        return _cip_status_reply(service, 0x08)

