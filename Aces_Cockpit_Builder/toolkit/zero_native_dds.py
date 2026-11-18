"""Lossless DDS container repair and headless Direct3D11 texture-load checks.

Dagor exports can advertise missing mip levels and append12 non-image bytes.
Preserve all complete image blocks; never decode/recompress them to repair a
header. Unknown truncation/layouts fail closed instead of inventing image data.
"""
import ctypes as C
import hashlib
from pathlib import Path
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize(data):
    assert data[:4] == b'DDS ' and len(data) >= 128
    header = list(struct.unpack_from('<31I', data, 4))
    assert header[0] == 124 and header[18] == 32
    height, width, declared = header[2], header[3], header[6] or 1
    assert height and width and header[5] == 0 and header[27] == 0, 'Only ordinary2D textures supported'
    fourcc = data[84:88]
    compressed = fourcc in (b'DXT1', b'DXT3', b'DXT5')
    if compressed:
        block = 8 if fourcc == b'DXT1' else 16
        sizes = [max(1, (max(1, width >> i) + 3)//4) *
                 max(1, (max(1, height >> i) + 3)//4) * block for i in range(declared)]
        pitch = sizes[0]
    else:
        assert header[19] & 0x40 and header[21] == 32, ('Unsupported DDS format', fourcc)
        sizes = [max(1, width >> i)*max(1, height >> i)*4 for i in range(declared)]
        pitch = width*4
    payload = data[128:]
    trailer = b''
    actual = declared
    if len(payload) != sum(sizes):
        assert compressed and len(payload) == sizes[0]+12 and declared > 1, (
            'Unknown truncated mip chain', width, height, declared, len(payload), sum(sizes))
        payload, trailer = payload[:sizes[0]], payload[sizes[0]:]
        actual = 1
    header[1] = 0x1007 | (0x80000 if compressed else 0x8) | (0x20000 if actual > 1 else 0)
    header[4], header[6] = pitch, actual
    header[26] = 0x1000 | (0x400008 if actual > 1 else 0)
    output = b'DDS ' + struct.pack('<31I', *header) + payload
    assert output[128:] == data[128:128+len(payload)], 'Image blocks changed'
    report = dict(width=width, height=height, format=fourcc.decode('ascii') if compressed else 'RGBA32',
                  declared_mips_before=declared, complete_mips_after=actual,
                  image_bytes=len(payload), removed_nonimage_bytes=len(trailer),
                  removed_bytes_hex=trailer.hex(), container_changed=output != data,
                  compressed_or_raw_image_blocks_byte_identical=True,
                  image_blocks_sha256=sha(payload), input_sha256=sha(data), output_sha256=sha(output))
    return output, report


def repair_file(path):
    path = Path(path)
    data, report = normalize(path.read_bytes())
    if report['container_changed']:
        path.write_bytes(data)
    # A second pass must do nothing, including on a repaired single mip.
    again, _ = normalize(data)
    assert again == data
    return report


class D3DProbe:
    """Create an independent offscreen WARP device. Never load/launch the game."""
    def __init__(self):
        d3d = C.WinDLL('d3d11')
        create = d3d.D3D11CreateDevice
        create.argtypes = [C.c_void_p, C.c_uint, C.c_void_p, C.c_uint, C.c_void_p,
                           C.c_uint, C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_uint),
                           C.POINTER(C.c_void_p)]
        create.restype = C.c_long
        self.device, self.context, feature = C.c_void_p(), C.c_void_p(), C.c_uint()
        hr = create(None, 5, None, 0, None, 0, 7, C.byref(self.device), C.byref(feature), C.byref(self.context))
        assert hr >= 0, ('D3D11 WARP device creation', hex(hr & 0xffffffff))
        self.library = C.WinDLL('d3dx11_43')
        self.load = self.library.D3DX11CreateShaderResourceViewFromFileW
        self.load.argtypes = [C.c_void_p, C.c_wchar_p, C.c_void_p, C.c_void_p,
                              C.POINTER(C.c_void_p), C.c_void_p]
        self.load.restype = C.c_long

    @staticmethod
    def release(obj):
        if obj.value:
            table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
            C.WINFUNCTYPE(C.c_ulong, C.c_void_p)(table[2])(obj)

    def check(self, path):
        resource = C.c_void_p()
        hr = self.load(self.device, str(Path(path).resolve()), None, None, C.byref(resource), None)
        self.release(resource)
        return dict(hresult=f'0x{hr & 0xffffffff:08x}', success=hr >= 0)

    def close(self):
        self.release(self.context)
        self.release(self.device)
