"""Minimal stdlib PE/COFF reader.

Deliberately dependency-free: this ships inside a skill and must run on a
release engineer's machine without a pip install. Parses only what build
fidelity comparison needs -- section map, the ephemeral header fields, and
the debug directory (PDB path, RSDS GUID, /Brepro marker).
"""
import struct

IMAGE_DEBUG_TYPE = {
    0: "UNKNOWN", 1: "COFF", 2: "CODEVIEW", 3: "FPO", 4: "MISC",
    5: "EXCEPTION", 6: "FIXUP", 7: "OMAP_TO_SRC", 8: "OMAP_FROM_SRC",
    9: "BORLAND", 10: "RESERVED10", 11: "CLSID", 12: "VC_FEATURE",
    13: "POGO", 14: "ILTCG", 15: "MPX", 16: "REPRO",
    17: "SPGO", 20: "EX_DLLCHARACTERISTICS",
}

MACHINE = {0x014C: "i386", 0x8664: "amd64", 0xAA64: "arm64", 0x01C4: "armnt"}


class NotPE(Exception):
    pass


class PE:
    """Parsed PE image. Every offset recorded here is a FILE offset."""

    def __init__(self, data):
        self.data = data
        if len(data) < 0x40 or data[:2] != b"MZ":
            raise NotPE("no MZ signature")
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            raise NotPE("no PE signature")

        coff = e_lfanew + 4
        (self.machine, self.n_sections, self.timestamp, _symtab, _nsyms,
         self.opt_size, self.characteristics) = struct.unpack_from("<HHIIIHH", data, coff)
        self.off_timestamp = coff + 4

        opt = coff + 20
        self.off_optional = opt
        self.magic = struct.unpack_from("<H", data, opt)[0]
        if self.magic == 0x20B:
            self.bits, n_dd_off, dd_off = 64, opt + 108, opt + 112
        elif self.magic == 0x10B:
            self.bits, n_dd_off, dd_off = 32, opt + 92, opt + 96
        else:
            raise NotPE("unknown optional header magic 0x%x" % self.magic)

        self.off_checksum = opt + 64
        self.checksum = struct.unpack_from("<I", data, self.off_checksum)[0]
        self.linker = (data[opt + 2], data[opt + 3])

        n_dd = struct.unpack_from("<I", data, n_dd_off)[0]
        self.data_dirs = []
        for i in range(min(n_dd, 16)):
            rva, size = struct.unpack_from("<II", data, dd_off + i * 8)
            self.data_dirs.append((rva, size))

        self.sections = []
        sec = opt + self.opt_size
        for i in range(self.n_sections):
            o = sec + i * 40
            if o + 40 > len(data):
                break
            name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
            chars = struct.unpack_from("<I", data, o + 36)[0]
            self.sections.append({
                "name": name, "vaddr": vaddr, "vsize": vsize,
                "raw_off": rawptr, "raw_size": rawsize,
                "characteristics": chars,
                "executable": bool(chars & 0x20000000),
                "code": bool(chars & 0x00000020),
            })

        self.cert = self.data_dirs[4] if len(self.data_dirs) > 4 else (0, 0)
        self.debug_entries = self._read_debug()

    # -- helpers ---------------------------------------------------------
    def rva_to_off(self, rva):
        for s in self.sections:
            span = max(s["vsize"], s["raw_size"])
            if s["raw_size"] and s["vaddr"] <= rva < s["vaddr"] + span:
                return s["raw_off"] + (rva - s["vaddr"])
        return None

    def section_at(self, off):
        for s in self.sections:
            if s["raw_size"] and s["raw_off"] <= off < s["raw_off"] + s["raw_size"]:
                return s
        first = self.sections[0]["raw_off"] if self.sections else len(self.data)
        if off < first:
            return {"name": "<headers>", "executable": False, "code": False}
        return None

    def _read_debug(self):
        out = []
        if len(self.data_dirs) < 7:
            return out
        rva, size = self.data_dirs[6]
        if not rva or not size:
            return out
        base = self.rva_to_off(rva)
        if base is None:
            return out
        for i in range(size // 28):
            o = base + i * 28
            if o + 28 > len(self.data):
                break
            (_ch, ts, _maj, _min, typ, dsize, _draw_rva,
             draw_off) = struct.unpack_from("<IIHHIIII", self.data, o)
            e = {
                "type": IMAGE_DEBUG_TYPE.get(typ, "TYPE_%d" % typ),
                "type_id": typ,
                "off_entry": o,
                "off_timestamp": o + 4,
                "timestamp": ts,
                "data_off": draw_off,
                "data_size": dsize,
            }
            if typ == 2 and draw_off and draw_off + 24 <= len(self.data):
                cv = self.data[draw_off:draw_off + dsize]
                if cv[:4] == b"RSDS" and len(cv) >= 24:
                    g = cv[4:20]
                    d1, d2, d3 = struct.unpack_from("<IHH", g, 0)
                    e["guid"] = "%08X-%04X-%04X-%s-%s" % (
                        d1, d2, d3, g[8:10].hex().upper(), g[10:16].hex().upper())
                    e["off_guid"] = draw_off + 4
                    e["age"] = struct.unpack_from("<I", cv, 20)[0]
                    e["pdb_path"] = cv[24:].split(b"\0")[0].decode("utf-8", "replace")
                    e["off_pdb_path"] = draw_off + 24
            out.append(e)
        return out

    # -- summary ---------------------------------------------------------
    @property
    def repro(self):
        return any(e["type_id"] == 16 for e in self.debug_entries)

    @property
    def pdb_path(self):
        for e in self.debug_entries:
            if "pdb_path" in e:
                return e["pdb_path"]
        return None

    @property
    def signed(self):
        return bool(self.cert[0] and self.cert[1])

    def ephemeral_fields(self):
        """File-offset ranges holding fields that are ephemeral by construction.

        This is the fast-path classifier only. Anything NOT covered here is
        handed to the model with string context rather than guessed at.
        """
        f = [(self.off_timestamp, 4, "coff.TimeDateStamp"),
             (self.off_checksum, 4, "optional.CheckSum")]
        for e in self.debug_entries:
            f.append((e["off_timestamp"], 4,
                      "debug[%s].TimeDateStamp" % e["type"]))
            if "off_guid" in e:
                f.append((e["off_guid"], 16, "debug.CODEVIEW.RSDS.Guid"))
                f.append((e["off_guid"] + 16, 4, "debug.CODEVIEW.RSDS.Age"))
            if "off_pdb_path" in e:
                f.append((e["off_pdb_path"], len(e["pdb_path"]) + 1,
                          "debug.CODEVIEW.RSDS.PdbPath"))
        if self.signed:
            f.append((self.cert[0], self.cert[1], "certificate_table"))
        return f

    def summary(self):
        return {
            "format": "pe",
            "machine": MACHINE.get(self.machine, hex(self.machine)),
            "bits": self.bits,
            "timestamp": self.timestamp,
            "checksum": self.checksum,
            "linker_version": "%d.%d" % self.linker,
            "repro": self.repro,
            "signed": self.signed,
            "pdb_path": self.pdb_path,
            "sections": [{k: s[k] for k in
                          ("name", "vaddr", "vsize", "raw_off", "raw_size")}
                         for s in self.sections],
            "debug": [{k: v for k, v in e.items() if not k.startswith("off_")}
                      for e in self.debug_entries],
        }


def load(path):
    with open(path, "rb") as fh:
        return PE(fh.read())


# ---------------------------------------------------------------------------
# Bare COFF objects and ar archives.
#
# Discovered empirically during zlib calibration: every .obj differed at file
# offset 4 (COFF TimeDateStamp) and every .lib differed at its member header
# date fields. Without these the fast path leaves them "unresolved" and the
# model is asked to adjudicate what is a known ephemeral field.
# ---------------------------------------------------------------------------

BIGOBJ_SIG = b"\x00\x00\xff\xff"
ARCHIVE_MAGIC = b"!<arch>\n"


class COFFObject:
    """Object file with no MZ/PE wrapper. COFF header sits at offset 0."""

    def __init__(self, data, base=0):
        self.data = data
        self.base = base
        self.bigobj = data[:4] == BIGOBJ_SIG
        if self.bigobj:
            # ANON_OBJECT_HEADER_BIGOBJ: sig(4) ver(2) machine(2) timestamp(4)
            self.machine = struct.unpack_from("<H", data, 6)[0]
            self.off_timestamp = 8
            self.sections = []
            return
        self.machine, self.n_sections, self.timestamp = struct.unpack_from(
            "<HHI", data, 0)
        if self.machine not in MACHINE:
            raise NotPE("offset-0 machine 0x%x not a known COFF machine"
                        % self.machine)
        self.off_timestamp = 4
        opt_size = struct.unpack_from("<H", data, 16)[0]
        self.sections = []
        sec = 20 + opt_size
        for i in range(min(self.n_sections, 4096)):
            o = sec + i * 40
            if o + 40 > len(data):
                break
            name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
            chars = struct.unpack_from("<I", data, o + 36)[0]
            self.sections.append({
                "name": name, "vaddr": vaddr, "vsize": vsize,
                "raw_off": rawptr, "raw_size": rawsize,
                "characteristics": chars,
                "executable": bool(chars & 0x20000000),
                "code": bool(chars & 0x00000020),
            })

    def section_at(self, off):
        off -= self.base
        for s in self.sections:
            if s["raw_size"] and s["raw_off"] <= off < s["raw_off"] + s["raw_size"]:
                return s
        return {"name": "<coff-header>", "executable": False, "code": False}

    def ephemeral_fields(self):
        return [(self.base + self.off_timestamp, 4, "coff.obj.TimeDateStamp")]

    def summary(self):
        return {"format": "coff-obj", "bigobj": self.bigobj,
                "machine": MACHINE.get(self.machine, hex(self.machine)),
                "sections": [s["name"] for s in self.sections]}


class Archive:
    """ar archive (MSVC .lib, GNU .a). Members carry their own timestamps."""

    def __init__(self, data):
        self.data = data
        if data[:8] != ARCHIVE_MAGIC:
            raise NotPE("no !<arch> magic")
        self.members = []
        off = 8
        while off + 60 <= len(data):
            hdr = data[off:off + 60]
            if hdr[58:60] != b"`\n":
                break
            name = hdr[0:16].rstrip().decode("ascii", "replace")
            try:
                size = int(hdr[48:58].decode("ascii").strip() or "0")
            except ValueError:
                break
            body = off + 60
            self.members.append({
                "name": name, "hdr_off": off, "off_date": off + 16,
                "body_off": body, "size": size,
            })
            off = body + size + (size & 1)          # members are 2-byte aligned
        self._children = {}
        for m in self.members:
            if m["name"].startswith("/") and not m["name"].strip("/").isdigit():
                continue                             # linker/longnames members
            blob = data[m["body_off"]:m["body_off"] + m["size"]]
            try:
                self._children[m["hdr_off"]] = COFFObject(blob, base=m["body_off"])
            except Exception:
                pass

    def _member_at(self, off):
        for m in self.members:
            if m["hdr_off"] <= off < m["body_off"] + m["size"]:
                return m
        return None

    def section_at(self, off):
        m = self._member_at(off)
        if m is None:
            return {"name": "<archive>", "executable": False, "code": False}
        child = self._children.get(m["hdr_off"])
        if child and off >= m["body_off"]:
            s = child.section_at(off)
            s = dict(s)
            s["name"] = "%s!%s" % (m["name"], s["name"])
            return s
        return {"name": "%s!<header>" % m["name"], "executable": False,
                "code": False}

    def ephemeral_fields(self):
        f = []
        for m in self.members:
            f.append((m["off_date"], 12, "ar.member[%s].Date" % m["name"]))
        for child in self._children.values():
            f.extend(child.ephemeral_fields())
        return f

    def summary(self):
        return {"format": "archive", "members": len(self.members),
                "coff_members": len(self._children)}


def inspect(data):
    """Return a parsed object exposing ephemeral_fields()/section_at(), or None."""
    if data[:8] == ARCHIVE_MAGIC:
        return Archive(data)
    if data[:2] == b"MZ":
        try:
            return PE(data)
        except NotPE:
            return None
    try:
        return COFFObject(data)
    except Exception:
        return None
