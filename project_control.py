"""Human project control: explicit membership, read-only snapshots and grounded next steps.

Snapshots and personal plans are distinct from Agent execution events. Nothing here
clones repositories, edits source, invokes a model, comments or creates a PR.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from project_discovery import ProjectDiscovery


REPO = re.compile(r'([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def repository_name(value):
    value = str(value or '').strip().rstrip('/').removesuffix('.git')
    if value.startswith('git@github.com:'):
        value = value.removeprefix('git@github.com:')
    elif '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https','ssh') or parsed.hostname != 'github.com':
            raise ValueError('请填写 GitHub 仓库 owner/repo 或 github.com 地址')
        value = parsed.path.strip('/').removesuffix('.git')
    if not REPO.fullmatch(value) or value.split('/')[1] in ('.','..'):
        raise ValueError('GitHub 仓库格式应为 owner/repo')
    return value


class GitHubError(ValueError):
    pass


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme!='https' or parsed.netloc!='api.github.com':
            raise GitHubError('GitHub 返回了不支持的重定向')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class GitHub:
    def get(self, path):
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise GitHubError('GitHub 请求路径无效')
        headers={'User-Agent':'Workhub/project-control','Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28'}
        token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if token:
            headers['Authorization']='Bearer '+token
        try:
            with build_opener(GitHubRedirect()).open(Request('https://api.github.com'+path,headers=headers),timeout=12) as response:
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:
                    raise GitHubError('GitHub 响应超出读取上限')
                return json.loads(raw),bool(response.headers.get('Link') and 'rel="next"' in response.headers['Link'])
        except HTTPError as error:
            raise GitHubError({401:'GitHub 凭据不可用',403:'GitHub 权限不足或已限流',404:'GitHub 仓库不存在或没有读取权限',429:'GitHub 已限流'}.get(error.code,'GitHub 暂时不可读')) from None
        except (URLError,TimeoutError,OSError,ValueError) as error:
            if isinstance(error,GitHubError):
                raise
            raise GitHubError('GitHub 暂时不可读，请稍后刷新') from None

    def catalog(self, owner):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',str(owner or '')):
            raise ValueError('请填写有效的 GitHub 用户名或组织名')
        rows,more=self.get('/users/'+owner+'/repos?type=owner&sort=pushed&per_page=100')
        if not isinstance(rows,list):
            raise GitHubError('GitHub 仓库列表格式无效')
        return {'repositories':[{'full_name':r['full_name'],'name':r['name'],'url':r['html_url'],
                                 'description':str(r.get('description') or '')[:500],
                                 'pushed_at':r.get('pushed_at'),'archived':r.get('archived',False)} for r in rows],
                'has_more':more,'observed_at':stamp(),'limit':100,'source':'GitHub public repository API'}

    def metadata(self, full_name):
        full_name=repository_name(full_name)
        data,_=self.get('/repos/'+full_name)
        return {'github_id':data['id'],'full_name':repository_name(data['full_name']),
                'url':'https://github.com/'+data['full_name'],'description':str(data.get('description') or '')[:500],
                'default_branch':data.get('default_branch'),'pushed_at':data.get('pushed_at'),
                'archived':bool(data.get('archived')),'open_items_count':data.get('open_issues_count')}

    def search(self,keywords):
        words=re.findall(r'[\w-]+',keywords,re.UNICODE)[:8]
        if not words:raise ValueError('请先填写检索关键词')
        query=' '.join('"'+word+'"' for word in words)+' in:name,description,readme is:public archived:false fork:false'
        path='/search/repositories?q='+quote(query,safe='')+'&per_page=10'
        data,more=self.get(path)
        if not isinstance(data.get('items'),list) or not isinstance(data.get('total_count'),int):
            raise GitHubError('GitHub 检索结果格式暂不可用')
        rows={}
        for item in data['items'][:10]:
            if item.get('private') or item.get('archived') or item.get('fork'):continue
            name=repository_name(item['full_name'])
            rows[item['id']]={'github_id':item['id'],'full_name':name,'url':'https://github.com/'+name,
                             'description':str(item.get('description') or '')[:700],'language':item.get('language'),
                             'stars':item.get('stargazers_count'),'pushed_at':item.get('pushed_at')}
        return {'keywords':keywords,'repositories':list(rows.values()),'total_count':data['total_count'],
                'incomplete':bool(data.get('incomplete_results',True)), 'has_more':more,'limit':10,
                'observed_at':stamp(),'source_url':'https://api.github.com'+path,'ranking':'keyword relevance'}

    def snapshot(self, full_name, expected_id=None):
        repo=self.metadata(full_name)
        if expected_id and repo['github_id']!=expected_id:
            raise GitHubError('仓库身份已变化，请重新确认接入')
        prefix='/repos/'+repo['full_name']
        result={'repository':repo,'observed_at':stamp(),'issues':[],'pull_requests':[],'actions':[],
                'sources':[],'errors':[],'limits':{},'head_sha':None}
        def read(key,path,transform):
            try:
                payload,more=self.get(path)
                result[key]=transform(payload)
                result['limits'][key]={'has_more':more,'sampled':True}
                result['sources'].append('https://api.github.com'+path)
            except (GitHubError,KeyError,TypeError,ValueError) as error:
                result['errors'].append({'source':key,'message':str(error) if isinstance(error,GitHubError) else 'GitHub 元数据格式暂不可用'})
        if repo['default_branch']:
            read('head_sha',prefix+'/commits/'+quote(repo['default_branch'],safe=''),lambda d:d['sha'])
        read('pull_requests',prefix+'/pulls?state=open&sort=updated&per_page=20',lambda ds:[
            {'number':d['number'],'title':str(d['title'])[:300],'url':d['html_url'],'draft':bool(d.get('draft')),'updated_at':d.get('updated_at')} for d in ds])
        read('issues',prefix+'/issues?state=open&sort=updated&per_page=30',lambda ds:[
            {'number':d['number'],'title':str(d['title'])[:300],'url':d['html_url'],'updated_at':d.get('updated_at')}
            for d in ds if 'pull_request' not in d])
        if result['head_sha']:
            sha=result['head_sha']
            read('actions',prefix+'/actions/runs?head_sha='+sha+'&per_page=30',lambda d:[
                {'id':r['id'],'workflow_id':r.get('workflow_id'),'name':str(r['name'])[:200],
                 'status':r['status'],'conclusion':r.get('conclusion'),'head_sha':r['head_sha'],'url':r['html_url']}
                for r in d['workflow_runs'] if r['head_sha']==sha])
        return result


def git_snapshot(path):
    directory=Path(path)
    env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')
    def git(*arguments,missing_ok=False):
        command=['git','--no-optional-locks','-c','core.fsmonitor=false','-c','diff.external=',
                 '-C',str(directory),*arguments]
        result=subprocess.run(command,env=env,capture_output=True,timeout=8)
        if result.returncode:
            if missing_ok:
                return ''
            raise ValueError('项目的 Git 元数据暂不可读')
        if len(result.stdout)>2*1024*1024:
            raise ValueError('Git 元数据超出读取上限')
        return result.stdout.decode('utf-8',errors='replace')
    if not directory.is_dir():
        raise ValueError('项目目录暂不可读')
    head=git('rev-parse','--verify','HEAD',missing_ok=True).strip() or None
    branch=git('branch','--show-current').strip() or '(detached HEAD)'
    raw=git('status','--porcelain=v1','-z','--untracked-files=normal')
    parts=raw.split('\0') if raw else []
    files=[];index=0
    while index<len(parts):
        entry=parts[index]
        if len(entry)>=3:
            files.append({'status':entry[:2],'path':entry[3:]})
            if 'R' in entry[:2] or 'C' in entry[:2]:
                index+=1
        index+=1
    # Only expose normalized repository names, never credential-bearing remote URLs.
    remote=None
    try:
        remote=repository_name(git('config','--get','remote.origin.url').strip())
    except ValueError:
        pass
    return {'observed_at':stamp(),'head_sha':head,'branch':branch,'changed_count':len(files),
            'changed_files':files[:20],'files_truncated':len(files)>20,'github_full_name':remote}


def recommendations(local=None, github=None, work_status=None):
    result=[]
    if work_status=='blocked':
        result.append({'kind':'blocked','priority':0,'title':'先处理已记录的阻塞','reason':'项目工作记录标为 blocked。','url':None})
    if local and local.get('changed_count'):
        result.append({'kind':'changes','priority':1,'title':'检查未提交改动','reason':'Git 当前有未提交文件；先核对差异，再决定下一步。','url':None})
    if github:
        if github.get('stale'):
            return sorted(result,key=lambda item:item['priority'])
        repo=github['repository']
        if repo.get('archived'):
            return result+[{'kind':'archived','priority':4,'title':'确认归档项目是否仍需关注','reason':'GitHub 仓库当前标记为 archived。','url':repo['url']}]
        latest={}
        for run in github.get('actions',[]):
            if run.get('head_sha')==github.get('head_sha'):
                key=run.get('workflow_id') or run['id']
                if key not in latest or run['id']>latest[key]['id']:
                    latest[key]=run
        for run in latest.values():
            if run['conclusion'] in ('failure','timed_out','action_required'):
                result.append({'kind':'ci','priority':0,'title':'查看当前提交的失败检查','reason':'GitHub Actions 对当前默认分支 SHA 返回失败。','url':run['url']})
            elif run['status']!='completed':
                result.append({'kind':'waiting','priority':3,'title':'等待当前提交的检查结果','reason':'对应当前默认分支 SHA 的工作流仍在运行。','url':run['url']})
        for row in github.get('pull_requests',[])[:1]:
            result.append({'kind':'pull_request','priority':2,'title':'检查最近更新的开放 PR','reason':'GitHub 中有仍开放的 PR；合并与否需要结合评审。','url':row['url']})
        for row in github.get('issues',[])[:1]:
            result.append({'kind':'issue','priority':2,'title':'安排尚未关闭的事项','reason':'GitHub 中有开放 Issue，可作为下一步的候选。','url':row['url']})
    return sorted(result,key=lambda item:item['priority'])[:6]


class ControlCenter:
    def __init__(self,store,workspace,github=None,start_scheduler=True,discovery_gap=7):
        self.store,self.workspace=store,workspace
        self.github=github or GitHub()
        self.executor=ThreadPoolExecutor(max_workers=3,thread_name_prefix='project-control')
        self.lock=threading.Lock();self.jobs={}
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS control_repositories (
                  id TEXT PRIMARY KEY,github_id INTEGER NOT NULL,full_name TEXT NOT NULL,
                  url TEXT NOT NULL,local_project_id TEXT,connected INTEGER NOT NULL DEFAULT 1,added_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS control_repository_identity ON control_repositories(github_id);
                CREATE TABLE IF NOT EXISTS control_snapshots (id TEXT PRIMARY KEY,payload TEXT NOT NULL,attempted_at TEXT NOT NULL,error TEXT);
                CREATE TABLE IF NOT EXISTS control_plans (id TEXT PRIMARY KEY,next_step TEXT NOT NULL DEFAULT '',priority INTEGER NOT NULL DEFAULT 2,updated_at TEXT NOT NULL);
            ''')
        self.discovery=ProjectDiscovery(store,self.members,self.github,self.executor,start_scheduler,discovery_gap)

    def close(self):
        self.discovery.close()
        self.executor.shutdown(wait=False,cancel_futures=True)

    def members(self):
        locals=self.workspace.projects()
        with self.store.connection() as db:
            remotes=[dict(r) for r in db.execute('SELECT * FROM control_repositories WHERE connected=1 ORDER BY added_at DESC')]
        result={p['id']:dict(p,kind='local') for p in locals}
        local_ids=set(result)
        for row in remotes:
            if row.get('local_project_id') and row['local_project_id'] not in local_ids:
                continue
            if row.get('local_project_id') in local_ids:
                result[row['local_project_id']]['repository']=row
            else:
                result[row['id']]=dict(row,kind='github',name=row['full_name'],path=None,repository=row,status=None)
        return result

    def connect(self,full_name,local_project_id=None):
        if local_project_id is not None and not self.workspace.contains(local_project_id):
            raise ValueError('关联的本地项目尚未手动加入中控')
        repo=self.github.metadata(full_name)
        identifier=hashlib.sha256(('github:'+str(repo['github_id'])).encode()).hexdigest()[:24]
        with self.store.connection() as db:
            if local_project_id:
                db.execute('UPDATE control_repositories SET connected=0 WHERE local_project_id=? AND id!=?',(local_project_id,identifier))
            db.execute('INSERT INTO control_repositories(id,github_id,full_name,url,local_project_id,connected,added_at) VALUES(?,?,?,?,?,1,?) '
                       'ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,url=excluded.url,local_project_id=excluded.local_project_id,connected=1',
                       (identifier,repo['github_id'],repo['full_name'],repo['url'],local_project_id,stamp()))
        return {'id':local_project_id or identifier,'repository':repo}

    def disconnect(self,identifier):
        members=self.members()
        if identifier not in members:
            raise ValueError('项目尚未手动加入中控')
        item=members[identifier]
        repository=item.get('repository')
        if not repository:
            raise ValueError('此项目没有连接 GitHub 仓库')
        with self.store.connection() as db:
            db.execute('UPDATE control_repositories SET connected=0 WHERE id=?',(repository['id'],))
        if item['kind']=='github':self.discovery.disable(identifier)
        return {'ok':True}

    def plan(self,identifier,next_step,priority=2):
        if identifier not in self.members():
            raise ValueError('项目尚未手动加入中控')
        if not isinstance(next_step,str) or len(next_step)>2000 or type(priority) is not int or priority not in range(4):
            raise ValueError('下一步最多 2000 字，优先级为 0 至 3')
        with self.store.connection() as db:
            db.execute('INSERT INTO control_plans(id,next_step,priority,updated_at) VALUES(?,?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET next_step=excluded.next_step,priority=excluded.priority,updated_at=excluded.updated_at',
                       (identifier,next_step.strip(),priority,stamp()))
        return {'ok':True}

    def refresh(self,identifier):
        member=self.members().get(identifier)
        if member is None:
            raise ValueError('项目尚未手动加入中控')
        with self.lock:
            if identifier in self.jobs:
                return {'accepted':True,'running':True}
            self.jobs[identifier]=True
        def task():
            payload={'local':None,'github':None,'errors':[],'observed_at':stamp()}
            try:
                if member['kind']=='local':
                    try:
                        payload['local']=git_snapshot(member['path'])
                    except (ValueError,OSError,subprocess.SubprocessError) as error:
                        payload['errors'].append('Git 元数据暂不可读')
                repository=member.get('repository')
                if repository:
                    try:
                        payload['github']=self.github.snapshot(repository['full_name'],repository['github_id'])
                    except GitHubError as error:
                        payload['errors'].append(str(error))
                with self.store.connection() as db:
                    previous=db.execute('SELECT payload FROM control_snapshots WHERE id=?',(identifier,)).fetchone()
                    old=json.loads(previous['payload']) if previous else {}
                    if payload.get('github') and repository:
                        refreshed=payload['github']['repository']
                        db.execute('UPDATE control_repositories SET full_name=?,url=? WHERE id=? AND github_id=?',
                                   (refreshed['full_name'],refreshed['url'],repository['id'],refreshed['github_id']))
                    for field in ('local','github'):
                        if payload[field] is None and old.get(field):
                            payload[field]=dict(old[field],stale=True)
                    current=payload.get('github')
                    previous=old.get('github')
                    if current and current.get('errors') and previous:
                        current['stale_fields']=[]
                        for failure in current['errors']:
                            field=failure['source']
                            if field in previous:
                                current[field]=previous[field]
                                current['stale_fields'].append(field)
                        if current['stale_fields']:
                            current['stale']=True
                    db.execute('INSERT INTO control_snapshots(id,payload,attempted_at,error) VALUES(?,?,?,?) '
                               'ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,attempted_at=excluded.attempted_at,error=excluded.error',
                               (identifier,json.dumps(payload,ensure_ascii=False),stamp(),'; '.join(payload['errors']) or None))
            finally:
                with self.lock:
                    self.jobs.pop(identifier,None)
        self.executor.submit(task)
        return {'accepted':True,'running':True}

    def state(self):
        members=self.members()
        discovery=self.discovery.configs()
        with self.store.connection() as db:
            snapshots={r['id']:dict(r) for r in db.execute('SELECT * FROM control_snapshots')}
            plans={r['id']:dict(r) for r in db.execute('SELECT * FROM control_plans')}
        rows=[]
        for identifier,item in members.items():
            raw=snapshots.get(identifier)
            snapshot=json.loads(raw['payload']) if raw else None
            if snapshot:
                linked=item.get('repository')
                cached=snapshot.get('github')
                if cached and (not linked or cached['repository']['github_id']!=linked['github_id']):
                    snapshot['github']=None
                    snapshot.setdefault('errors',[]).append('仓库连接已改变，请刷新快照')
                for field in ('local','github'):
                    saved=snapshot.get(field)
                    if saved:
                        try:
                            age=(datetime.now(timezone.utc)-datetime.fromisoformat(saved['observed_at'].replace('Z','+00:00'))).total_seconds()
                            if age>900: saved['stale']=True
                        except (KeyError,ValueError,TypeError):
                            saved['stale']=True
            row={'id':identifier,'name':item['name'],'kind':item['kind'],'path':item.get('path'),
                 'work_status':item.get('status'),'repository':item.get('repository'),
                 'snapshot':snapshot,'plan':plans.get(identifier),'refreshing':identifier in self.jobs}
            row['discovery']=discovery.get(identifier,{'keywords':'','enabled':False,'interval_hours':24,'results':None,'running':False,'stale':False})
            row['recommendations']=recommendations((snapshot or {}).get('local'),(snapshot or {}).get('github'),row['work_status'])
            rows.append(row)
        rows.sort(key=lambda r:((r['plan'] or {}).get('priority',2), min((x['priority'] for x in r['recommendations']),default=9),r['name'].casefold()))
        return {'projects':rows,'observed_at':stamp(),'manual_membership':True}
