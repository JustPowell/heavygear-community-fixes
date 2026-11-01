/* Compile-only check of the generated d3d9_min.h for the 32-bit Windows target: layouts the D3D9 runtime expects,
 * and a use of every method the backend will call, so a wrong prototype fails here and not in the game. */
#include "../d3d9_min.h"

_Static_assert(sizeof(D3DPRESENT_PARAMETERS) == 56, "D3DPRESENT_PARAMETERS is 14 dwords on x86");
_Static_assert(sizeof(D3DLOCKED_RECT) == 8, "D3DLOCKED_RECT is pitch and pointer");
_Static_assert(sizeof(D3DVIEWPORT9) == 24, "D3DVIEWPORT9 is six dwords");
_Static_assert(sizeof(D3DFORMAT) == 4, "enums are 32 bits");
_Static_assert(D3DFVF_XYZRHW == 0x004 && D3DFVF_DIFFUSE == 0x040 && D3DFVF_SPECULAR == 0x080 && D3DFVF_TEX1 == 0x100, "FVF flags");
_Static_assert(D3DRS_FOGENABLE == 28 && D3DRS_FOGCOLOR == 34 && D3DRS_FOGTABLEMODE == 35 && D3DRS_FOGVERTEXMODE == 140, "fog render states");
_Static_assert(D3DFMT_A8R8G8B8 == 21 && D3DFMT_R5G6B5 == 23 && D3DFMT_D24S8 == 75, "formats");
_Static_assert(D3DRS_ZENABLE == 7 && D3DRS_ALPHABLENDENABLE == 27 && D3DRS_FOGENABLE == 28, "render states");

int use_all(IDirect3D9 *d3d, IDirect3DDevice9 *dev, IDirect3DTexture9 *tex, HWND wnd)
{
    IDirect3DSurface9 *bb = 0, *sys = 0;
    IDirect3DQuery9 *qry = 0;
    D3DPRESENT_PARAMETERS pp = {0};
    D3DDISPLAYMODE dm;
    D3DLOCKED_RECT lr;
    D3DVIEWPORT9 vp = {0, 0, 640, 480, 0.0f, 1.0f};
    float verts[7] = {0};
    DWORD q;
    int r = 0;
    pp.BackBufferWidth = 640; pp.BackBufferHeight = 480; pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.hDeviceWindow = wnd; pp.Windowed = 1;
    pp.EnableAutoDepthStencil = 1; pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_ONE;
    r |= d3d->lpVtbl->GetAdapterDisplayMode(d3d, D3DADAPTER_DEFAULT, &dm);
    r |= d3d->lpVtbl->CheckDeviceMultiSampleType(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, D3DFMT_X8R8G8B8, 1, D3DMULTISAMPLE_4_SAMPLES, &q);
    r |= d3d->lpVtbl->CreateDevice(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd, D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE, &pp, &dev);
    r |= dev->lpVtbl->TestCooperativeLevel(dev);
    r |= dev->lpVtbl->Reset(dev, &pp);
    r |= dev->lpVtbl->CreateTexture(dev, 256, 256, 0, D3DUSAGE_AUTOGENMIPMAP, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, (HANDLE *)0);
    r |= dev->lpVtbl->BeginScene(dev);
    r |= dev->lpVtbl->Clear(dev, 0, (const D3DRECT *)0, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_ARGB(255, 0, 0, 0), 1.0f, 0);
    r |= dev->lpVtbl->SetViewport(dev, &vp);
    r |= dev->lpVtbl->SetRenderState(dev, D3DRS_ZENABLE, 1);
    r |= dev->lpVtbl->SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    r |= dev->lpVtbl->SetTexture(dev, 0, (IDirect3DBaseTexture9 *)tex);
    r |= dev->lpVtbl->SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    r |= dev->lpVtbl->SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    r |= dev->lpVtbl->SetFVF(dev, D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1);
    r |= dev->lpVtbl->DrawPrimitiveUP(dev, D3DPT_TRIANGLEFAN, 1, verts, 28);
    r |= dev->lpVtbl->EndScene(dev);
    r |= dev->lpVtbl->Present(dev, (const RECT *)0, (const RECT *)0, wnd, (const RGNDATA *)0);
    r |= tex->lpVtbl->LockRect(tex, 0, &lr, (const RECT *)0, D3DLOCK_DISCARD);
    r |= tex->lpVtbl->UnlockRect(tex, 0);
    r |= dev->lpVtbl->GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    r |= dev->lpVtbl->CreateOffscreenPlainSurface(dev, 640, 480, D3DFMT_X8R8G8B8, D3DPOOL_SYSTEMMEM, &sys, (HANDLE *)0);
    r |= dev->lpVtbl->GetRenderTargetData(dev, bb, sys);
    r |= sys->lpVtbl->LockRect(sys, &lr, (const RECT *)0, D3DLOCK_READONLY);
    r |= sys->lpVtbl->UnlockRect(sys);
    sys->lpVtbl->Release(sys); bb->lpVtbl->Release(bb);
    r |= dev->lpVtbl->CreateQuery(dev, D3DQUERYTYPE_EVENT, &qry);
    r |= qry->lpVtbl->Issue(qry, D3DISSUE_END);
    r |= qry->lpVtbl->GetData(qry, (void *)0, 0, D3DGETDATA_FLUSH);
    qry->lpVtbl->Release(qry);
    tex->lpVtbl->GenerateMipSubLevels(tex);
    tex->lpVtbl->Release(tex); dev->lpVtbl->Release(dev); d3d->lpVtbl->Release(d3d);
    return r;
}
