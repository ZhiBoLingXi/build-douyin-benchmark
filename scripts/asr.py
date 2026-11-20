"""Local multilingual transcription worker (MLX Whisper or faster-whisper)."""
import json
import sys
from pathlib import Path

media, model, lang = sys.argv[1:]
language = None if lang == 'auto' else lang
try:
    import mlx_whisper
except ImportError:
    from faster_whisper import WhisperModel
    engine = WhisperModel(model,device='cpu',compute_type='int8',local_files_only=True)
    segments,info=engine.transcribe(media,language=language,word_timestamps=True,vad_filter=True)
    lines=[dict(start=s.start,end=s.end,text=s.text,words=[dict(start=w.start,end=w.end,word=w.word) for w in (s.words or [])]) for s in segments]
    language=info.language
else:
    if not Path(model).is_dir(): raise ValueError('MLX requires a local model directory')
    out=mlx_whisper.transcribe(media,path_or_hf_repo=model,language=language,word_timestamps=True,condition_on_previous_text=False,hallucination_silence_threshold=2.0,verbose=None)
    language=out['language'];lines=[{k:s.get(k) for k in ('start','end','text','words')} for s in out['segments']]
print(json.dumps({'status':'machine','language':language,'segments':lines},ensure_ascii=False))
