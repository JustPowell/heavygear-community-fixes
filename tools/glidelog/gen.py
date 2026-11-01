# generates glidelog.c and glide2x.def: a logging proxy for glide2x.dll. Every export of the real driver (exports.txt) is wrapped: hot calls get a custom logger, the rest log their arguments and return value
imports = open('exports.txt').read().split()
custom = {'grChromakeyMode','grChromakeyValue','grTexSource','grTexDownloadTable','grTexDownloadMipMap',
          'grDrawTriangle','grColorCombine','grAlphaBlendFunction','grAlphaCombine','grTexCombine',
          'grConstantColorValue','grFogMode','grDrawPolygonVertexList','grAADrawLine','grBufferSwap','grSstWinOpen','grGlideShutdown','grDrawPoint','grDrawLine'}
out=[open('glidelog_head.c').read()]
# declare every real-function pointer first so wrappers can call each other's targets
for _imp in imports:
    _n, _b = _imp[1:].split('@'); _k = int(_b)//4
    out.append('typedef U (__stdcall *t_%s)(%s); static t_%s r_%s;' % (_n, ', '.join(['U']*_k) or 'void', _n, _n))
defs=['LIBRARY glide2x','EXPORTS']
names=[]
for imp in imports:
    name, n = imp[1:].split('@'); n=int(n)//4
    names.append((name,n))
    args=', '.join(f'U a{i}' for i in range(n)) or 'void'
    call=', '.join(f'a{i}' for i in range(n))
    tdef=', '.join(['U']*n) or 'void'
    if name == 'grDrawTriangle':
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); return r_{name}({call}); }}')
    elif name == 'grChromakeyMode':
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); return r_{name}(fx_fix ? 0 : a0); }}')
    elif name == 'grTexSource':
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); return fx_texsource({call}); }}')
    elif name == 'grTexDownloadTable':
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); return r_{name}({call}); }}')
    elif name == 'grChromakeyValue':
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); fx_lastkey = a0; return r_{name}({call}); }}')
    elif name in custom:
        out.append(f'U __stdcall {name}({args}) {{ log_{name}({call}); return r_{name}({call}); }}')
    else:
        pa = ''.join(f' put_s(" "); put_x(a{i});' for i in range(min(n,8)))
        out.append(f'U __stdcall {name}({args}) {{ force_line = 1; hdr("{name}");{pa} put_s(")"); flush_line(); U r = r_{name}({call}); hdr("  ret"); put_x(r); put_s(")"); flush_line(); force_line = 0; return r; }}')
    defs.append(imp)
defs.append('hgCaptureNative=_hgCaptureNative@4')
out.append('static void resolve(HMOD h) {')
for name,n in names:
    out.append(f'  r_{name} = (t_{name})GetProcAddress(h, "_{name}@{n*4}");')
out.append('}')
out.append(open('glidelog_tail.c').read())
open('glidelog.c','w').write('\n'.join(out))
open('glide2x.def','w').write('\n'.join(defs)+'\n')
