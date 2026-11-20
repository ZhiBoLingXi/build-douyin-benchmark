"""Package the reviewed account analysis as a self-contained Codex authoring skill."""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from media import write


def package(root,destination):
    state=json.loads((root/'account.json').read_text())
    profile=state['profile']; uid=str(profile.get('uid') or '')
    key=uid if uid.isdigit() else hashlib.sha256(profile['sec_uid'].encode()).hexdigest()[:16]
    name='douyin-playbook-'+key
    rows=[];analyzed=[];entries=[];csvbuf=io.StringIO()
    writer=csv.writer(csvbuf);writer.writerow(['作品 ID','北京时间','作品类型','发布文案','作品链接','本次取样'])
    for w in state['works']:
        vid=w['id'];selected=vid in state['selected'];date=datetime.fromtimestamp(w['published'],ZoneInfo('Asia/Shanghai')).isoformat() if w['published'] else ''
        writer.writerow([vid,date,w['kind'],w['title'],w['url'],selected])
        if not selected:continue
        sub=root/'analysis'/vid
        if not (root/'videos'/(vid+'.mp4')).is_file():continue
        if not all((sub/f).is_file() for f in ('逐字稿.txt','逐字稿.srt','分镜表.html','分镜表.csv','shots.json','transcript.json','review.json')):continue
        sh=json.loads((sub/'shots.json').read_text());rev=json.loads((sub/'review.json').read_text())
        if not sh or not all(rev.get(str(s['shot']),{}).get('action') for s in sh):continue
        analyzed.append(vid)
        rows.append(f'| {date[:10]} | [{vid}]({w["url"]}) | {len(sh)} |')
        links=[(f'videos/{vid}.mp4','视频'),(f'analysis/{vid}/逐字稿.txt','逐字稿'),(f'analysis/{vid}/逐字稿.srt','字幕'),(f'analysis/{vid}/分镜表.html','图文分镜'),(f'analysis/{vid}/分镜表.csv','CSV')]
        entries.append('<tr><td>'+date[:10]+'</td><td>'+html.escape(w['title'])+'</td><td>'+' · '.join(f'<a href="{quote(p)}">{label}</a>' for p,label in links)+'</td></tr>')
    write(root/'视频列表.csv','\ufeff'+csvbuf.getvalue())
    if not analyzed:raise SystemExit('还没有经过画面复核且含转写的样本，不能生成账号创作技能')
    inputs={}
    for f in ('账号与受众.md','创作模板.md'):
        text=(root/f).read_text().strip()
        if not text or not any(v in text for v in analyzed):
            raise ValueError(f+' 需要至少一条已拆作品 ID 作为依据')
        inputs[f]=text
    n=len(analyzed); want=len(state['selected'])
    coverage=f'已拆 {n}/{want} 条入选作品，当前列表 {len(state["works"])} 项；列表与排序完整核验：'+('是' if state['ordering_verified'] else '否，仅为当前可见样本')
    write(root/'拉片索引.html','<!doctype html><meta charset="utf-8"><title>账号拉片索引</title><style>body{max-width:1050px;margin:38px auto;font:16px system-ui}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}</style><h1>'+html.escape(profile['nickname'])+'</h1><p>'+coverage+'</p><p><a href="视频列表.csv">作品列表</a> · <a href="账号与受众.md">账号与受众</a> · <a href="创作模板.md">创作模板</a></p><table><tr><th>发布日</th><th>作品文案</th><th>素材</th></tr>'+''.join(entries)+'</table>')
    destination.mkdir(parents=True,exist_ok=True);target=destination/name
    if target.exists():raise FileExistsError(f'技能目录已存在：{target}。更新时先在新目录构建并比较已有编辑。')
    nick=profile['nickname'];tag=json.dumps
    desc=f'用{nick}公开样本提炼的内容结构，为独立新账号设计人设、选题、脚本和制作分镜。适用于用户点名参考这个账号或调用本对标技能时。'
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        stage=Path(tmp)/name;(stage/'references').mkdir(parents=True);(stage/'agents').mkdir()
        write(stage/'SKILL.md',f"""---
name: {name}
description: {tag(desc,ensure_ascii=False)}
---

# 参考{nick}的新账号创作

先读[账号、人设与受众](references/account.md)和[模板、变体与原创示例](references/formats.md)。[样本索引](references/samples.md)记录覆盖范围及作品来源。{coverage}。

收到“起号”时，结合用户的题材、产品、资源或出镜意愿，给出新账号的观众承诺、独立角色、观众关注理由和三个可连拍的选题。用户只给产品时，先把功效翻译成观众能看见的动作和结果，再出选题。每个候选写出头两秒的具体画面、观众会追问什么、关键翻转以及适用模板。保留让用户选题的环节；用户指定题目或要求直接成稿时进入脚本。

选定后按模板交付可拍的视频脚本：按秒写首帧、人物动作、景别或机位、对白、画面字、声音、切点和结尾；给出实现关键镜头的拍摄或 AI 生成提示，并说明商品或信息如何改变情节。为新账号另取名、另设视觉标识、角色和口头表达，用原创情节验证抽象方法。面向观众的稿件使用新账号自己的身份。

来源样本的观察与观众画像推断分开。只有起号内容或提出复盘需求时使用该方法；有新账号自己的数据后据其反馈调整模板。
""")
        write(stage/'references/account.md',inputs['账号与受众.md']+'\n')
        write(stage/'references/formats.md',inputs['创作模板.md']+'\n')
        write(stage/'references/samples.md',f'# {nick} 样本\n\n采样 {state["collected_at"]} · {coverage}。\n\n[作者主页]({profile["homepage"]})\n\n| 发布日期 | 作品 ID 与原链接 | 候选分镜段数 |\n|---|---|---:|\n'+'\n'.join(rows)+'\n')
        short='用公开样本提炼的人设、钩子和视频模板，为独立新账号策划选题与脚本'
        write(stage/'agents/openai.yaml',f'interface:\n  display_name: {tag(nick+"对标创作",ensure_ascii=False)}\n  short_description: {tag(short,ensure_ascii=False)}\n  default_prompt: {tag("用 $"+name+" 为我的新账号策划三个可拍的原创选题。",ensure_ascii=False)}\n')
        os.rename(stage,target)
    print(target)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--dest',required=True,type=Path)
    a=p.parse_args();package(a.out.resolve(),a.dest.expanduser().resolve())
