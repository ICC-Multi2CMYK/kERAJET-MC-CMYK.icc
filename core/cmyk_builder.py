from __future__ import annotations
import hashlib
import struct
from pathlib import Path
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree
from .icc_reader import analyze_icc


def u32(b, o): return struct.unpack_from('>I', b, o)[0]

def align4(b): return b + b'\0' * ((-len(b)) % 4)

def parse_tags(data):
    n = u32(data, 128)
    out = []
    for i in range(n):
        p = 132 + 12 * i
        out.append((data[p:p+4].decode('latin1'), u32(data, p+4), u32(data, p+8)))
    return out

def tag_map(data): return {s: data[o:o+z] for s, o, z in parse_tags(data)}

def parse_curves(tag, start, count):
    curves = []
    p = start
    for _ in range(count):
        if p + 12 > len(tag) or tag[p:p+4] != b'curv':
            raise ValueError('Curva ICC inesperada o incompleta')
        n = u32(tag, p + 8)
        size = 12 if n == 0 else 16 if n == 1 else 12 + 2 * n
        size = (size + 3) // 4 * 4
        if p + size > len(tag):
            raise ValueError('Curva ICC fuera de rango')
        curves.append(tag[p:p+size])
        p += size
    return curves

def curve_values(curve):
    n = u32(curve, 8)
    x = np.linspace(0, 1, 4096)
    if n == 0:
        return x
    if n == 1:
        gamma = u32(curve, 12) / 65536.0
        return np.power(x, gamma)
    vals = np.frombuffer(curve[12:12+2*n], dtype='>u2').astype(np.float64) / 65535.0
    return np.interp(x, np.linspace(0, 1, n), vals)

def make_table_curve(vals):
    vals = np.clip(np.asarray(vals, dtype=np.float64), 0, 1)
    q = np.rint(vals * 65535).astype('>u2').tobytes()
    return align4(b'curv' + b'\0\0\0\0' + struct.pack('>I', len(vals)) + q)

def extract_mab(tag):
    typ = tag[:4]
    inch = tag[8]
    outch = tag[9]
    B = u32(tag, 12)
    M = u32(tag, 20)
    C = u32(tag, 24)
    A = u32(tag, 28)
    if M:
        raise ValueError('El perfil contiene una matriz MPE en la LUT; esta versión solo admite LUT sin matriz.')
    if not C:
        raise ValueError('LUT sin CLUT')
    bcount, acount = (outch, inch) if typ == b'mAB ' else (inch, outch)
    bcurves = parse_curves(tag, B, bcount) if B else []
    acurves = parse_curves(tag, A, acount) if A else []
    grid = list(tag[C:C+16])[:inch]
    prec = tag[C+16]
    if prec != 2:
        raise ValueError(f'CLUT de {prec*8} bits no compatible; se requiere 16-bit')
    if any(g < 2 for g in grid):
        raise ValueError(f'CLUT inválida: {grid}')
    cells = int(np.prod(grid))
    raw = tag[C+20:C+20+cells*outch*2]
    if len(raw) != cells*outch*2:
        raise ValueError('CLUT truncada o incompatible con su dimensión declarada')
    vals = np.frombuffer(raw, dtype='>u2').astype(np.float64) / 65535.0
    return {'type': typ, 'in_ch': inch, 'out_ch': outch, 'grid': grid,
            'bcurves': bcurves, 'acurves': acurves, 'vals': vals}

def _curve_eval_vector(curve, x):
    vals = curve_values(curve)
    return np.interp(np.asarray(x, dtype=np.float64), np.linspace(0, 1, vals.size), vals)

def eval_source_a2b_on_first4(comp, res=17):
    """Reduce an arbitrary N-channel A2B LUT to a 4-channel CMYK subspace.

    The first four device channels are sampled on a 4D grid while channels 5..N
    are fixed at device code 0.  The source A-curves are applied before the CLUT.
    The last dimension of the ICC CLUT is the fastest-varying dimension; numpy's
    C-order reshape matches that convention when the flattened ICC values are
    reshaped as grid + output_channels.
    """
    n = comp['in_ch']
    if n < 4:
        raise ValueError('El perfil debe tener al menos 4 canales de dispositivo.')
    if comp['out_ch'] < 3:
        raise ValueError('La LUT debe tener al menos 3 canales PCS.')

    grid = comp['grid']
    vals = comp['vals'].reshape(tuple(grid) + (comp['out_ch'],))
    axes = [np.linspace(0, 1, g) for g in grid]
    interp = RegularGridInterpolator(tuple(axes), vals, bounds_error=False, fill_value=None)

    coords = np.linspace(0, 1, res)
    m = np.stack(np.meshgrid(coords, coords, coords, coords, indexing='ij'), axis=-1).reshape(-1, 4)

    # Apply input A-curves to the four active channels.
    active = []
    for j in range(4):
        if j < len(comp['acurves']):
            active.append(_curve_eval_vector(comp['acurves'][j], m[:, j]))
        else:
            active.append(m[:, j])
    q = np.stack(active, axis=1)

    # Remaining channels are fixed at device code 0 and are passed through their A-curves.
    tail = []
    for j in range(4, n):
        z = np.zeros(m.shape[0], dtype=np.float64)
        if j < len(comp['acurves']):
            z = np.full_like(z, float(_curve_eval_vector(comp['acurves'][j], np.array([0.0]))[0]))
        tail.append(z)
    full = np.concatenate([q, np.stack(tail, axis=1)], axis=1) if tail else q
    outv = interp(full)
    # Apply source B-curves after the CLUT when present (mAB: B curves are output/PCS curves).
    outv = np.asarray(outv, dtype=np.float64)
    for j in range(min(comp['out_ch'], len(comp['bcurves']))):
        outv[:, j] = _curve_eval_vector(comp['bcurves'][j], outv[:, j])
    return outv.reshape((res, res, res, res, comp['out_ch']))

def make_mab(tag_type, inch, outch, bcurves, grid, vals, acurves):
    h = bytearray(32)
    h[:4] = tag_type
    h[8] = inch
    h[9] = outch
    pos = 32
    data = bytearray(h)

    Boff = pos if bcurves else 0
    if bcurves:
        data += b''.join(bcurves)
        data = bytearray(align4(bytes(data)))
        pos = len(data)

    # 16-byte CLUT header: 16 grid bytes, precision byte at +16, 3 reserved bytes.
    clut_head = bytes(grid) + b'\0' * (16 - len(grid)) + bytes([2, 0, 0, 0])
    clut = clut_head + b''.join(struct.pack('>H', int(x)) for x in np.asarray(vals, dtype=np.uint16).tolist())
    Coff = pos
    data += clut
    data = bytearray(align4(bytes(data)))
    pos = len(data)

    Aoff = pos if acurves else 0
    if acurves:
        data += b''.join(acurves)
        data = bytearray(align4(bytes(data)))
        pos = len(data)

    struct.pack_into('>I', data, 12, Boff)
    struct.pack_into('>I', data, 16, 0)  # Matrix
    struct.pack_into('>I', data, 20, 0)  # M curves
    struct.pack_into('>I', data, 24, Coff)
    struct.pack_into('>I', data, 28, Aoff)
    return bytes(data)

def mluc(text):
    raw = text.encode('utf-16-be')
    out = bytearray(b'mluc\0\0\0\0')
    out += struct.pack('>II', 1, 12) + b'enUS' + struct.pack('>II', len(raw), 28) + raw
    return align4(bytes(out))

def reduced_clrt(tag):
    if tag[:4] != b'clrt' or u32(tag, 8) < 4:
        return None
    b = bytearray(tag)
    struct.pack_into('>I', b, 8, 4)
    for i, n in enumerate((b'Cyan', b'Magenta', b'Yellow', b'Black')):
        p = 12 + i * 38
        b[p:p+32] = n.ljust(32, b'\0')
    return align4(bytes(b[:12 + 4 * 38]))

def _make_a2b_and_inverse(big, comp, a2b_res, b2a_res):
    # 'big' is already the fully evaluated source transform, including source A/B curves.
    # Therefore the new CMYK A2B must use identity curves; otherwise curves would be applied twice.
    identity = make_table_curve(np.linspace(0,1,4096))
    a2b_vals = np.rint(np.clip(big, 0, 1) * 65535).astype(np.uint16).reshape(-1).tolist()
    a2b = make_mab(b'mAB ', 4, 3, [identity] * 3, [a2b_res] * 4, a2b_vals, [identity] * 4)

    internal = np.stack(np.meshgrid(*([np.linspace(0,1,a2b_res)]*4), indexing='ij'), axis=-1).reshape(-1,4)
    sample_lab = big.reshape(-1, 3)
    lab_xyz = np.column_stack([
        sample_lab[:, 0] * 100.0,
        sample_lab[:, 1] * 255.0 - 128.0,
        sample_lab[:, 2] * 255.0 - 128.0,
    ])
    tree = cKDTree(lab_xyz)
    q = np.linspace(0, 1, b2a_res)
    L, A, B = np.meshgrid(q, q, q, indexing='ij')
    targets = np.column_stack([
        L.reshape(-1) * 100.0,
        A.reshape(-1) * 255.0 - 128.0,
        B.reshape(-1) * 255.0 - 128.0,
    ])
    k = min(16, len(sample_lab))
    d, idx = tree.query(targets, k=k)
    if np.ndim(d) == 1:
        d = d[:, None]
        idx = idx[:, None]
    w = 1.0 / (d + 1e-6)
    w /= w.sum(axis=1, keepdims=True)
    chosen = (internal[idx] * w[..., None]).sum(axis=1)
    b2a_vals = np.rint(np.clip(chosen, 0, 1) * 65535).astype(np.uint16).reshape(-1).tolist()
    identity = make_table_curve(np.linspace(0,1,4096))
    b2a = make_mab(b'mBA ', 3, 4, [], [b2a_res] * 3, b2a_vals, [identity] * 4)
    return a2b, b2a

def build_one_intent(source_tags, sig, a2b_res=17, b2a_res=33):
    comp = extract_mab(source_tags[sig])
    big = eval_source_a2b_on_first4(comp, a2b_res)
    return _make_a2b_and_inverse(big, comp, a2b_res, b2a_res)

def build_from_source(source: Path, output: Path, description: str, copyright_text: str = '', intent: int = 1, a2b_res: int = 17, b2a_res: int = 33):
    source_data = source.read_bytes()
    tags = tag_map(source_data)
    a = analyze_icc(source)
    if a['channels'] < 4:
        raise ValueError('El perfil fuente debe tener al menos 4 canales (CMYK + especiales).')
    for t in ['wtpt', 'chad', 'clrt', 'A2B0', 'A2B1', 'A2B2']:
        if t not in tags:
            raise ValueError(f'Falta tag {t}')
    new = {'desc': mluc(description), 'wtpt': tags['wtpt'], 'chad': tags['chad'], 'cprt': tags.get('cprt', b'')}
    clrt = reduced_clrt(tags['clrt'])
    if clrt:
        new['clrt'] = clrt

    for i, sig in enumerate(('A2B0', 'A2B1', 'A2B2')):
        a2b, b2a = build_one_intent(tags, sig, a2b_res, b2a_res)
        new[sig] = a2b
        new[f'B2A{i}'] = b2a

    h = bytearray(source_data[:128])
    h[12:16] = b'prtr'
    h[16:20] = b'CMYK'
    h[20:24] = b'Lab '
    h[84:100] = b'\0' * 16
    data = bytearray(h)
    data += struct.pack('>I', len(new))
    data += b'\0' * (12 * len(new))

    for i, (sig, blob) in enumerate(new.items()):
        off = len(data)
        data += blob
        data += b'\0' * (-len(data) % 4)
        p = 132 + i * 12
        data[p:p+4] = sig.encode('latin1')
        struct.pack_into('>I', data, p+4, off)
        struct.pack_into('>I', data, p+8, len(blob))

    struct.pack_into('>I', data, 0, len(data))
    data[84:100] = hashlib.md5(bytes(data)).digest()
    output.write_bytes(data)

    # Summarize source geometry for UI/debugging.
    geometries = {}
    for sig in ('A2B0', 'A2B1', 'A2B2'):
        c = extract_mab(tags[sig])
        geometries[sig] = {'channels': c['in_ch'], 'grid': c['grid']}

    return {
        'output': str(output),
        'description': description,
        'source_channels': a['channel_names'][:4],
        'source_total_channels': a['channels'],
        'source_geometry': geometries,
        'strategy': 'Genérico CMYK+N: se usan los 4 primeros canales; especiales 5..N=0; se evalúa el A2B fuente completo (A+CLUT+B) y se encapsula una nueva A2B CMYK con curvas identidad para evitar doble aplicación; B2A 33^3 se reconstruye como inversa.',
        'tags_written': list(new.keys()),
    }
