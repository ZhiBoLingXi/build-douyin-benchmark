"""Read one public author's published works and download the ten newest videos."""
import argparse
import json
import os
import re
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import douyin_download as dy


def save(p, data):
    with tempfile.NamedTemporaryFile('w', encoding='utf8', dir=p.parent, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(f.name, p)


def detail(browser, vid):
    page = browser.new_page()
    try:
        with page.expect_response(lambda r: urlsplit(r.url).path.rstrip('/').endswith('/aweme/detail'), timeout=24000) as pending:
            page.goto('https://open.douyin.com/player/video?vid='+vid, wait_until='domcontentloaded', timeout=35000)
        obj = pending.value.json().get('aweme_detail') or {}
        if str(obj.get('aweme_id')) != vid or not obj.get('author', {}).get('sec_uid'):
            raise ValueError('作品详情未确认作者或作品 ID')
        return obj
    finally:
        page.close()


def row(item):
    stats = item.get('statistics') or {}
    return {'id': str(item['aweme_id']), 'title':item.get('desc',''), 'published':item.get('create_time'),
            'kind':'image' if item.get('images') or item.get('image_infos') or item.get('aweme_type') in (2,68,150) else ('video' if item.get('video') else 'unknown'),
            'url':'https://www.douyin.com/video/'+str(item['aweme_id']),
            'metrics':{k:stats[k] for k in ('digg_count','comment_count','share_count','collect_count') if k in stats}}


def desktop_catalog(browser, sec, items):
    """Listen only to the author's Works tab, including pages loaded by scrolling."""
    page=browser.new_page()
    cursors=set()
    ended=False
    def capture(response):
        nonlocal ended
        url=urlsplit(response.url)
        if url.hostname!='www.douyin.com' or url.path.rstrip('/')!='/aweme/v1/web/aweme/post' or sec not in parse_qs(url.query).get('sec_user_id',[]):return
        try:data=response.json()
        except Exception:return
        posts=data.get('aweme_list')
        if data.get('status_code')!=0 or not isinstance(posts,list):return
        for item in posts:
            if str((item.get('author') or {}).get('sec_uid'))==sec and re.fullmatch(dy.ID,str(item.get('aweme_id',''))):
                items[str(item['aweme_id'])]=row(item)
        cursors.add(str(data.get('max_cursor')))
        ended=data.get('has_more') in (False,0)
    try:
        page.on('response',capture)
        page.goto('https://www.douyin.com/user/'+sec,wait_until='domcontentloaded',timeout=35000)
        page.wait_for_timeout(4200)
        while not ended and cursors:
            before=len(cursors)
            cards=page.locator('[data-e2e="user-post-list"] a[href*="/video/"]')
            if not cards.count():break
            cards.last.scroll_into_view_if_needed(timeout=3500)
            page.mouse.wheel(0,1100)
            for _ in range(10):
                page.wait_for_timeout(300)
                if ended or len(cursors)>before:break
            if len(cursors)==before:break
    except Exception:pass
    finally:page.close()
    return ended


def catalog(browser, author):
    sec = author['sec_uid']
    url = 'https://www.iesdouyin.com/share/user/'+sec
    ctx = browser.new_context(user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1', viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    items, user, finished, why = {}, {}, False, ''
    try:
        def feed(r):
            u=urlsplit(r.url)
            params=parse_qs(u.query)
            return u.hostname in ('www.iesdouyin.com','www.douyin.com','www.amemv.com') and u.path.rstrip('/').endswith('/aweme/post') and (sec in params.get('sec_uid',[]) or sec in params.get('sec_user_id',[]))
        data=None
        for attempt in range(2):
            try:
                with page.expect_response(feed, timeout=18000) as pending:
                    page.goto(url,wait_until='domcontentloaded',timeout=35000)
                response=pending.value
                data=json.loads(response.body())
                if data.get('status_code')==0 and isinstance(data.get('aweme_list'),list):break
            except Exception:
                if attempt:raise
                page.wait_for_timeout(600)
        link=urlsplit(response.url)
        original=parse_qs(link.query)
        params={k:original[k] for k in ('sec_uid','sec_user_id','count') if k in original}
        cursors=set()
        while True:
            if data.get('status_code') != 0 or not isinstance(data.get('aweme_list'),list):
                why='作品分页未返回有效列表'; break
            for item in data['aweme_list']:
                if re.fullmatch(dy.ID,str(item.get('aweme_id',''))) and (item.get('author') or {}).get('sec_uid',sec)==sec:
                    items[str(item['aweme_id'])]=row(item)
            if data.get('has_more') in (False,0):
                finished=True;break
            cursor=str(data.get('max_cursor') or '')
            if not cursor or cursor in cursors:
                why='分页游标缺失或重复';break
            cursors.add(cursor)
            params['max_cursor']=[cursor]
            next_url=urlunsplit((link.scheme,link.netloc,link.path,urlencode(params,doseq=True),''))
            resp=ctx.request.get(next_url,timeout=25000)
            if not resp.ok:
                why='下一页 HTTP '+str(resp.status);break
            data=resp.json()
    except Exception as exc:
        why='官方作品分页读取失败：'+type(exc).__name__
    finally:
        try:
            store=page.evaluate("() => Object.values(window._ROUTER_DATA?.loaderData || {}).find(x=>x?.userInfoRes)?.userInfoRes?.user_info || {}")
            if store.get('sec_uid')==sec:user=store
        except Exception:pass
        ctx.close()
    profile={k:user.get(k,author.get(k)) for k in ('uid','sec_uid','unique_id','nickname','signature','aweme_count','custom_verify','total_favorited')}
    if not finished:
        finished=desktop_catalog(browser,sec,items)
        why='' if finished else (why or '官方页面未返回末页')
    declared=profile.get('aweme_count')
    if finished and isinstance(declared,int) and len(items)<declared:
        finished=False;why=f'公开返回 {len(items)} 项，主页声明 {declared} 项'
    profile['homepage']='https://www.douyin.com/user/'+sec
    profile['catalog_url']=url
    profile['following_count']=user.get('following_count')
    profile['displayed_follower_index']=user.get('mplatform_followers_count')
    return profile, items, finished, why


def run(a):
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    f=out/'account.json'
    shares=list(dy.tokens(a.share))
    if len(shares)!=1: raise ValueError('请输入一条作品分享链接')
    vid=dy.resolve(shares[0])
    with ExitStack() as stack:
        browser=dy.launch(stack)
        if f.exists():
            state=json.loads(f.read_text())
            if vid!=state['seed_id']:raise ValueError('目录已用于其他输入；请使用新目录')
        else:
            state={'seed_id':vid,'collected_at':datetime.now(timezone.utc).isoformat(),'downloads':{},'verified_ids':[]}
        if not state.get('catalog_complete') or not state.get('profile'):
            source=detail(browser,vid); author=source['author']
            profile, items, done, why=catalog(browser,author)
            if state.get('profile',{}).get('sec_uid',author['sec_uid'])!=author['sec_uid']:raise ValueError('账号身份变化')
            previous={w['id']:w for w in state.get('works',[])}
            merged={} if done else previous.copy()
            checked=set(state.get('verified_ids',[]))
            for wid,current in items.items():
                if wid in checked and wid in previous:
                    current={**current,**previous[wid]}
                merged[wid]=current
            old_profile=state.get('profile',{})
            profile={k:(v if v is not None and v!='' else old_profile.get(k,v)) for k,v in profile.items()}
            state.update(profile=profile,works=list(merged.values()),catalog_complete=done,catalog_issue=why,
                         verified_ids=sorted(checked.intersection(merged)))
            save(f,state)
        works=state['works']
        checked=set(state['verified_ids'])
        if getattr(a,'work_links',None):
            by_id={w['id']:w for w in works}
            ignored=[]
            for token in dy.tokens(a.work_links.read_text()):
                candidate=dy.resolve(token)
                if candidate in by_id:continue
                try:
                    obj=detail(browser,candidate)
                    if obj['author']['sec_uid']!=state['profile']['sec_uid']:raise ValueError('作者不匹配')
                    by_id[candidate]=row(obj);checked.add(candidate)
                except Exception:ignored.append(candidate)
            state['supplement']={'origin':state['profile']['homepage'],'rejected_ids':ignored}
            works=list(by_id.values());state['works']=works
            declared=state['profile'].get('aweme_count')
            if declared==len(works) and not ignored:
                state.update(catalog_complete=True,catalog_issue='',coverage_basis='作者主页作品栏补录，作品数与主页声明一致')
            state['verified_ids']=sorted(checked);save(f,state)
        for item in works:
            if item['id'] in checked or (item['published'] and item['kind'] in ('image','video')):continue
            try:
                richer=detail(browser,item['id'])
                if richer['author']['sec_uid']!=state['profile']['sec_uid']:raise ValueError('作者不匹配')
                item.update(row(richer))
                if not item['published']:raise ValueError('缺少发布时间')
                checked.add(item['id']);item.pop('detail_error',None)
            except Exception as exc:
                item['detail_error']=type(exc).__name__
            state['verified_ids']=sorted(checked);save(f,state)
        works.sort(key=lambda x:(x.get('published') or 0,x['id']),reverse=True)
        complete=state['catalog_complete'] and all(w['kind']=='image' or (w['kind']=='video' and w['published'] and not w.get('detail_error')) for w in works)
        state['ordering_verified']=bool(complete)
        state['selected']=[w['id'] for w in works if w['kind']=='video' and w['published'] and not w.get('detail_error')][:10]
        save(f,state)
        print(json.dumps({k:state[k] for k in ('catalog_complete','catalog_issue','ordering_verified','selected')},ensure_ascii=False),flush=True)
        if getattr(a,'list_only',False):return 0 if complete else 1
        for id_ in state['selected']:
            try:
                result=dy.download(id_,SimpleNamespace(output=out/'videos',require_audio=False),lambda:browser)
            except Exception as exc:
                result={'status':'failed','error':dy.error_text(exc)}
            state['downloads'][id_]=result;save(f,state)
            print(id_,result['status'],flush=True)
        return 0 if complete and all(state['downloads'][v]['status'] in ('existing','saved') for v in state['selected']) else 1


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True,type=Path);ap.add_argument('share',nargs='?');ap.add_argument('--list-only',action='store_true');ap.add_argument('--work-links',type=Path)
    args=ap.parse_args()
    if not args.share:args.share=sys.stdin.read()
    sys.exit(run(args))
