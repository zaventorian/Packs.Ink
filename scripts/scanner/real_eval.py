"""
Run the pipeline on the user's REAL phone photos (data/real/*.jpg). Mirrors the
shipped worker (CLAHE before Canny, multi-epsilon quad, relaxed aspect) so what
Python detects ~= what the worker detects. Saves, per photo:
  data/real_out/<name>_quad.jpg   original with the detected quad drawn
  data/real_out/<name>_rect.png   the rectified+normalised card (what gets matched)
and a contact sheet of all rectified cards + the colour-matcher's top-3 guess.

  python scripts/scanner/real_eval.py
"""
from __future__ import annotations
import glob, json, os, sys
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DATA = HERE/"data"; IMG = DATA/"img"; REAL = DATA/"real"; OUT = DATA/"real_out"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D

def order_quad(pts):
    s=pts.sum(1); d=pts[:,1]-pts[:,0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)

def detect_quad(rgb):
    h,w=rgb.shape[:2]; procW=480; sc=procW/w; procH=int(h*sc)
    small=cv2.resize(rgb,(procW,procH))
    gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    gray=cv2.createCLAHE(3.0,(8,8)).apply(gray)
    blur=cv2.GaussianBlur(gray,(5,5),0)
    edges=cv2.Canny(blur,40,120)
    edges=cv2.dilate(edges,np.ones((7,7),np.uint8))
    cnts,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    best=None;bestscore=0;area_img=procW*procH
    def consider(q, contour_area):
        nonlocal best,bestscore
        w1=np.linalg.norm(q[0]-q[1]); w2=np.linalg.norm(q[3]-q[2])
        h1=np.linalg.norm(q[0]-q[3]); h2=np.linalg.norm(q[1]-q[2])
        wq=(w1+w2)/2; hq=(h1+h2)/2
        if min(wq,hq)<20: return
        rect=(min(w1,w2)/max(w1,w2))*(min(h1,h2)/max(h1,h2))
        if rect<0.6: return
        ar=min(wq,hq)/max(wq,hq)
        arsc=1-min(1,abs(ar-5/7)/0.26)
        if arsc<=0: return
        # the quad area should mostly be filled by the contour (rejects a
        # min-area-rect that bounds a sprawling non-card contour)
        quad_area=wq*hq; fill=min(1, contour_area/(quad_area+1e-6))
        if fill<0.7: return
        score=arsc*0.35+rect*0.3+fill*0.2+min(1,(quad_area/(procW*procH)))*0.15
        if score>bestscore: bestscore=score; best=q/sc
    for c in cnts:
        a=cv2.contourArea(c)
        if a<area_img*0.05: continue
        peri=cv2.arcLength(c,True)
        # (1) clean 4-point quad (best for perspective)
        got=False
        for ep in (0.02,0.035,0.05,0.07):
            ap=cv2.approxPolyDP(c,ep*peri,True)
            if len(ap)==4 and cv2.isContourConvex(ap):
                consider(order_quad(ap.reshape(4,2).astype(np.float32)), a); got=True; break
        # (2) fallback: best-fit rotated rectangle (robust to imperfect/merged edges)
        box=cv2.boxPoints(cv2.minAreaRect(c))
        consider(order_quad(box.astype(np.float32)), a)
    return best

def rectify(rgb,quad,normalize=False):
    wq=(np.linalg.norm(quad[0]-quad[1])+np.linalg.norm(quad[3]-quad[2]))/2
    hq=(np.linalg.norm(quad[0]-quad[3])+np.linalg.norm(quad[1]-quad[2]))/2
    outW,outH=(560,400) if wq>hq else (360,504)
    dst=np.array([[0,0],[outW,0],[outW,outH],[0,outH]],np.float32)
    M=cv2.getPerspectiveTransform(quad.astype(np.float32),dst)
    warp=cv2.warpPerspective(rgb,M,(outW,outH))
    if not normalize: return warp
    lab=cv2.cvtColor(warp,cv2.COLOR_RGB2LAB); l,a,b=cv2.split(lab)
    l=cv2.createCLAHE(2.5,(8,8)).apply(l)
    return cv2.cvtColor(cv2.merge([l,a,b]),cv2.COLOR_LAB2RGB)

def main():
    OUT.mkdir(exist_ok=True)
    idx=json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8")); meta=idx["cards"]
    art=np.array([c["art_key"] for c in meta])
    ref=np.zeros((len(meta),432),np.float32)
    for i,c in enumerate(meta):
        p=IMG/f"{c['id']}.avif"
        if p.exists(): ref[i]=D.color_sig(Image.open(p).convert("RGB"))
    files=sorted(glob.glob(str(REAL/"*.jpg")))
    files=[f for f in files if "_contact" not in f]
    rects=[]
    def cmatch(rgbimg):
        qv=D.color_sig(Image.fromarray(rgbimg)); s=ref@qv; o=np.argsort(-s)[:3]
        return [ (meta[i]["name"]+(" - "+meta[i]["version"] if meta[i].get("version") else "")) for i in o ]
    for f in files:
        name=Path(f).stem[:8]
        rgb=np.asarray(Image.open(f).convert("RGB"))
        quad=detect_quad(rgb); detected=quad is not None
        if detected:
            rect=rectify(rgb,quad,normalize=False)
            rectn=rectify(rgb,quad,normalize=True)
            vis=rgb.copy(); cv2.polylines(vis,[quad.astype(np.int32)],True,(0,255,0),8)
        else:
            H,W=rgb.shape[:2]; gh=int(H*0.82); gw=int(gh*5/7)
            rect=rgb[max(0,(H-gh)//2):(H+gh)//2, max(0,(W-gw)//2):(W+gw)//2]; rectn=rect
            vis=rgb.copy()
        Image.fromarray(vis).resize((300,int(300*rgb.shape[0]/rgb.shape[1]))).save(OUT/f"{name}_quad.jpg",quality=85)
        Image.fromarray(rect).save(OUT/f"{name}_rect.png")
        top_raw=cmatch(rect); top_norm=cmatch(rectn)
        rects.append((name, detected, rect, top_raw))
        print(f"{name}  det={detected}  RAW: {top_raw[0]:<34}  NORM: {top_norm[0]}")
    # contact sheet of rectified cards
    cols=4; rows=(len(rects)+cols-1)//cols; tw,th=200,300
    sheet=Image.new("RGB",(cols*tw,rows*th),(15,15,15)); d=ImageDraw.Draw(sheet)
    for i,(name,det,rect,top) in enumerate(rects):
        im=Image.fromarray(rect); im.thumbnail((tw-8,th-40))
        x=(i%cols)*tw; y=(i//cols)*th; sheet.paste(im,(x+4,y+4))
        d.text((x+6,y+th-34),name+(" OK" if det else " NODET"),fill=(120,255,120) if det else (255,120,120))
        d.text((x+6,y+th-20),top[0][:24],fill=(255,255,150))
    sheet.save(OUT/"_rectified.jpg",quality=88)
    print("\nsaved contact sheet of rectified cards:", OUT/"_rectified.jpg")

if __name__=="__main__":
    main()
