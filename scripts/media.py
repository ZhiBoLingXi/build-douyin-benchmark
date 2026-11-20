"""Extract shot evidence and time-coded speech for the selected source videos."""
import argparse
import csv
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image,ImageDraw


def write(path, text):
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
        f.write(text)
    os.replace(f.name,path)


def js(path,x):
    write(path,json.dumps(x,ensure_ascii=False,indent=2)+'\n')


def stamp(t):
    ms=max(0,round(t*1000))
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'


def frames(video,folder,seconds):
    log=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-i',str(video),'-an','-vf',"scale=320:-2,select='gt(scene,0.20)',showinfo",'-f','null','-'],stderr=subprocess.PIPE,text=True,check=True).stderr
    cuts=[0.]
    for txt in re.findall(r'\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:\s*([\d.]+)', log):
        t=float(txt)
        if t-cuts[-1]>=.14 and seconds-t>=.14:cuts.append(t)
    grid_dir=folder/'frames';grid_dir.mkdir(exist_ok=True)
    shots=[];thumbs=[]
    for i,(a,b) in enumerate(zip(cuts,cuts[1:]+[seconds]),1):
        times=[round(a+(b-a)*k,3) for k in (.12,.5,.86)]
        imgs=[]
        for t in times:
            proc=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(max(0,min(t,seconds-.1))),'-i',str(video),'-frames:v','1','-vf','scale=360:240:force_original_aspect_ratio=decrease','-f','image2pipe','-c:v','mjpeg','-'],capture_output=True,check=True)
            if not proc.stdout and imgs: imgs.append(imgs[-1].copy());continue
            if not proc.stdout:raise ValueError(f'未能解出 {t}s 的帧')
            imgs.append(Image.open(io.BytesIO(proc.stdout)).convert('RGB'))
        w,h=max(x.width for x in imgs),max(x.height for x in imgs)
        strip=Image.new('RGB',(w*3,h+22),'#181818');draw=ImageDraw.Draw(strip)
        for col,img in enumerate(imgs):
            strip.paste(img,(col*w,22));draw.text((col*w+4,4),f'S{i:02}  {times[col]:.2f}s',fill='white')
        rel=f'frames/S{i:03}.jpg';strip.save(folder/rel,quality=86)
        thumb=strip.copy();thumb.thumbnail((660,160));thumbs.append(thumb)
        shots.append({'shot':i,'start':round(a,3),'end':round(b,3),'frames':rel,'sample_times':times})
    for start in range(0,len(thumbs),8):
        batch=thumbs[start:start+8];sheet=Image.new('RGB',(max(v.width for v in batch),sum(v.height for v in batch)), '#181818')
        y=0
        for img in batch:sheet.paste(img,(0,y));y+=img.height
        sheet.save(folder/f'contact-{start//8+1:02}.jpg',quality=84)
    return shots


def render(folder,shots,tr):
    segs=tr.get('segments',[])
    txt=''.join(f'[{stamp(s["start"])} – {stamp(s["end"])}] {s["text"].strip()}\n' for s in segs)
    write(folder/'逐字稿.txt',f'状态 {tr["status"]} | 语言 {tr.get("language") or "未知"}\n'+txt)
    write(folder/'逐字稿.srt',''.join(f'{i}\n{stamp(s["start"])} --> {stamp(s["end"])}\n{s["text"].strip()}\n\n' for i,s in enumerate(segs,1)))
    review_path=folder/'review.json'
    notes=json.loads(review_path.read_text()) if review_path.exists() else {}
    keys=['镜号','开始秒','结束秒','切点性质','画面动作','景别和机位','对白或旁白','可见字幕','声音线索','叙事作用','关键帧']
    buf=io.StringIO();writer=csv.writer(buf);writer.writerow(keys)
    rows=[]
    for sh in shots:
        a,b=sh['start'],sh['end'];selected=[]
        for s in segs:
            words=s.get('words') or []
            if words:
                selected+= [w['word'] for w in words if a<=(w['start']+w['end'])/2<b]
            elif a<=s['start']<b:selected.append(s['text'])
        n=notes.get(str(sh['shot']),{})
        vals=[sh['shot'],a,b,n.get('boundary','自动候选'),n.get('action',''),n.get('camera',''),n.get('speech',''.join(selected).strip()),n.get('caption',''),n.get('sound',''),n.get('function',''),sh['frames']]
        writer.writerow(vals)
        cells=''.join('<td>'+html.escape(str(v))+'</td>' for v in vals[:-1])
        rows.append('<tr>'+cells+'<td><a href="'+sh['frames']+'"><img width="420" src="'+sh['frames']+'"></a></td></tr>')
    write(folder/'分镜表.csv','\ufeff'+buf.getvalue())
    write(folder/'分镜表.html','<!doctype html><meta charset="utf-8"><title>分镜表</title><style>body{font:14px sans-serif}td,th{border:1px solid #bbb;padding:5px;vertical-align:top}table{border-collapse:collapse}</style><table><tr>'+''.join('<th>'+k+'</th>' for k in keys)+'</tr>'+''.join(rows)+'</table>')


def asr_runtime(python, model):
    cache=Path(os.environ.get('HF_HUB_CACHE',Path(os.environ.get('HF_HOME',Path.home()/'.cache/huggingface'))/'hub'))
    if not model:
        candidates=sorted(cache.glob('models--mlx-community--whisper*/snapshots/*'),key=lambda p: ('large-v3-turbo' in str(p),str(p)),reverse=True)
        model=next((str(p) for p in candidates if (p/'weights.safetensors').is_file() or (p/'weights.npz').is_file()),None)
    if not model:raise ValueError('未找到本地语音模型，请指定 --model')
    if not python:
        is_mlx=(Path(model)/'weights.safetensors').exists() or (Path(model)/'weights.npz').exists()
        mod='mlx_whisper' if is_mlx else 'faster_whisper'
        candidates=[sys.executable]
        executable=shutil.which('mlx_whisper') if is_mlx else None
        if executable:candidates.append(str(Path(executable).parent/'python'))
        if is_mlx:candidates.extend(str(p.parent/'python') for p in sorted((Path.home()/'.cache/uv/archive-v0').glob('*/bin/mlx_whisper')))
        for candidate in dict.fromkeys(candidates):
            if os.path.isfile(candidate) and subprocess.run([candidate,'-c','import importlib.util,sys; sys.exit(importlib.util.find_spec(sys.argv[1]) is None)',mod],capture_output=True).returncode==0:
                python=candidate;break
    if not python:raise ValueError('未找到带转写引擎的解释器，请指定 --asr-python')
    return python,model


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--step',choices=['frames','asr','render','all'],default='all');ap.add_argument('--language',default='auto');ap.add_argument('--asr-python');ap.add_argument('--model');ap.add_argument('--id',action='append')
    a=ap.parse_args();state=json.loads((a.out/'account.json').read_text());failed=False
    for vid in state['selected']:
        if a.id and vid not in a.id:continue
        meta=state['downloads'].get(vid,{})
        if meta.get('status') not in ('saved','existing'):failed=True;continue
        folder=a.out/'analysis'/vid;folder.mkdir(parents=True,exist_ok=True)
        source=a.out/'videos'/(vid+'.mp4');sp=folder/'shots.json';tp=folder/'transcript.json'
        try:
            if a.step in ('frames','all') and not sp.exists():js(sp,frames(source,folder,meta['seconds']))
            if a.step in ('asr','all') and not tp.exists():
                if not meta['audio_codecs']:tr={'status':'no_audio','segments':[]}
                else:
                    a.asr_python,a.model=asr_runtime(a.asr_python,a.model)
                    task=subprocess.run([a.asr_python,str(Path(__file__).with_name('asr.py')),str(source),a.model,a.language],capture_output=True,text=True)
                    if task.returncode:raise RuntimeError(task.stderr[-650:])
                    tr=json.loads(task.stdout.strip().splitlines()[-1])
                    if not tr['segments']:tr['status']='no_speech_detected'
                js(tp,tr)
            if a.step in ('render','all'):
                render(folder,json.loads(sp.read_text()),json.loads(tp.read_text()))
            print(vid,a.step,'OK',flush=True)
        except Exception as exc:
            failed=True;print(vid,a.step,str(exc),file=sys.stderr,flush=True)
    return int(failed)


if __name__=='__main__':sys.exit(main())
