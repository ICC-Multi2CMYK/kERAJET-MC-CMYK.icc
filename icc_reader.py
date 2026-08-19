import struct
from pathlib import Path

SIG_TO_SPACE = {b'RGB ': 'RGB', b'CMYK': 'CMYK', b'Lab ': 'Lab', b'XYZ ': 'XYZ', b'8CLR': '8CLR'}

def u32(b, o): return struct.unpack_from('>I', b, o)[0]
def s32(b, o): return struct.unpack_from('>i', b, o)[0]

def parse_mluc(data, off, size):
    if data[off:off+4] != b'mluc': return ''
    count = u32(data, off+8)
    rec_off = off+16
    if count < 1: return ''
    # first record, UTF-16BE
    length = u32(data, rec_off+4)
    pos = u32(data, rec_off+8)
    raw = data[off+pos:off+pos+length]
    return raw.decode('utf-16-be', errors='replace').rstrip('\x00')

def channel_names_from_clrt(data, tag_off):
    # ICC colorantTable entries are 38 bytes: 32-byte device colorant name
    # followed by 3x 16-bit XYZ values. Do not infer channel identity from names.
    if data[tag_off:tag_off+4] != b'clrt': return []
    count = u32(data, tag_off+8)
    names=[]
    entry_off = tag_off+12
    for i in range(count):
        p = entry_off + i*38
        if p+10 > len(data): break
        # colorant names occupy the first 32 bytes of each 38-byte entry.
        raw=data[p:p+32].split(b'\x00',1)[0]
        try: name=raw.decode('ascii', errors='replace').strip()
        except: name=''
        names.append(name)
    return names

def parse_tag_table(data):
    n=u32(data,128)
    tags=[]
    for i in range(n):
        p=132+i*12
        sig=data[p:p+4].decode('latin1')
        off=u32(data,p+4); size=u32(data,p+8)
        typ=data[off:off+4].decode('latin1', errors='replace') if off+4<=len(data) else ''
        tags.append({'signature':sig,'type':typ,'offset':off,'size':size})
    return tags

def curve_summary(curves):
    out=[]
    for c in curves:
        vals=c.get('values_norm',[])
        out.append({'count':c.get('count'), 'kind':c.get('kind'), 'first':vals[0] if vals else None, 'mid':vals[len(vals)//2] if vals else None, 'last':vals[-1] if vals else None, 'values_norm': vals})
    return out

def parse_curves(data, start, count):
    curves=[]; p=start
    for _ in range(count):
        typ=data[p:p+4]
        if typ != b'curv': break
        n=u32(data,p+8)
        if n==0:
            curves.append({'type':'curv','count':0,'kind':'identity','values_norm':[],'offset':p,'size':12})
            p += 12
            continue
        if n==1:
            g=s32(data,p+12)/65536.0
            curves.append({'type':'curv','count':1,'kind':'gamma','gamma':g,'values_norm':[],'offset':p,'size':16})
            p += 16
        else:
            vals=[]; q=p+12
            for i in range(n): vals.append(struct.unpack_from('>H',data,q+2*i)[0]/65535.0)
            size=12+2*n
            size=(size+3)//4*4
            curves.append({'type':'curv','count':n,'kind':'table','values_norm':vals,'offset':p,'size':size})
            p += size
    return curves

def parse_mab(data, tag):
    off=tag['offset']; typ=data[off:off+4]
    in_ch=data[off+8]; out_ch=data[off+9]
    B_off=u32(data,off+12)
    matrix_off=u32(data,off+16)
    M_off=u32(data,off+20)
    CLUT_off=u32(data,off+24)
    A_off=u32(data,off+28)
    # mBA ordering differs: B, matrix, M, CLUT, A fields have same positions.
    curves1=[]; curves2=[]
    if B_off:
        # mAB: B curves are output channels; mBA: B curves are input channels.
        curves1=parse_curves(data, off+B_off, out_ch if typ==b'mAB ' else in_ch)
    if A_off:
        # mAB: A curves are input channels; mBA: A curves are output channels.
        curves2=parse_curves(data, off+A_off, in_ch if typ==b'mAB ' else out_ch)
    clut=None
    if CLUT_off:
        p=off+CLUT_off
        grid=list(data[p:p+16])[:in_ch]
        precision=data[p+16]
        vals_start=p+20
        cell_count=1
        for g in grid: cell_count*=g
        count=cell_count*out_ch
        vals=[]
        for i in range(count):
            vals.append(struct.unpack_from('>H',data,vals_start+2*i)[0])
        clut={'grid':grid,'precision_bits':precision*8,'output_channels':out_ch,'values_u16':vals,'value_count':len(vals)}
    return {'type':typ.decode('latin1'),'input_channels':in_ch,'output_channels':out_ch,'B_curves':curve_summary(curves1),'A_curves':curve_summary(curves2),'clut':clut}

def analyze_icc(path: Path):
    data=path.read_bytes()
    color_space=data[16:20]
    pcs=data[20:24]
    version=f'{data[8]}.{data[9]>>4}.{data[9]&0x0F}'
    cls=data[12:16].decode('latin1')
    tags=parse_tag_table(data)
    desc=''
    for t in tags:
        if t['signature']=='desc': desc=parse_mluc(data,t['offset'],t['size'])
    names=[]
    for t in tags:
        if t['signature']=='clrt': names=channel_names_from_clrt(data,t['offset'])
    luts={}
    for sig in ['A2B0','A2B1','A2B2','B2A0','B2A1','B2A2']:
        t=next((x for x in tags if x['signature']==sig),None)
        if t:
            luts[sig]=parse_mab(data,t)
    return {'file':path.name,'size':len(data),'version':version,'class':cls,'color_space':SIG_TO_SPACE.get(color_space,color_space.decode('latin1')),'pcs':SIG_TO_SPACE.get(pcs,pcs.decode('latin1')),'description':desc,'tags':tags,'channels':len(names),'channel_names':names,'luts':luts}

def raw_tag_bytes(data: bytes, signature: str):
    for t in parse_tag_table(data):
        if t['signature'] == signature:
            return bytes(data[t['offset']:t['offset']+t['size']])
    return b''
