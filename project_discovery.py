"""Opt-in project discovery while Workhub runs; persistent leases prevent duplicate searches."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading
import time
import uuid
from project_comparison import compare, safe_text


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


class ProjectDiscovery:
    def __init__(self,store,members,github,executor,start_scheduler=True,gap_seconds=7):
        self.store,self.members,self.github,self.executor=store,members,github,executor
        self.gap=gap_seconds;self.stop=threading.Event();self.lock=threading.Lock();self.jobs=set()
        with store.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS control_discovery (
                id TEXT PRIMARY KEY,keywords TEXT NOT NULL DEFAULT '',enabled INTEGER NOT NULL DEFAULT 0,
                interval_hours INTEGER NOT NULL DEFAULT 24,generation INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT,last_run_at TEXT,last_error TEXT,results TEXT,lease TEXT,lease_until REAL NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS control_discovery_budget (id INTEGER PRIMARY KEY,last_started REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS control_discovery_seen (id TEXT NOT NULL,github_id INTEGER NOT NULL,PRIMARY KEY(id,github_id));
              INSERT OR IGNORE INTO control_discovery_budget(id,last_started) VALUES(1,0);
            ''')
            if 'project_focus' not in {r[1] for r in db.execute('PRAGMA table_info(control_discovery)')}:
                db.execute("ALTER TABLE control_discovery ADD COLUMN project_focus TEXT NOT NULL DEFAULT ''")
        self.thread=None
        if start_scheduler:
            self.thread=threading.Thread(target=self.loop,daemon=True,name='project-discovery-clock');self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)

    def configs(self):
        members=self.members()
        with self.store.connection() as db:
            data={r['id']:dict(r) for r in db.execute('SELECT * FROM control_discovery')}
        for row in data.values():
            row['enabled']=bool(row['enabled']);row['results']=json.loads(row['results']) if row['results'] else None
            row['running']=row['id'] in self.jobs or row['lease_until']>time.time()
            row['stale']=bool(row['last_error']) or bool(row['results'] and (row['results']['keywords']!=row['keywords'] or row['results'].get('project_focus','')!=row['project_focus']))
            if row['results'] and row['results'].get('comparison_version'):
                current=(members.get(row['id'],{}).get('repository') or {}).get('github_id')
                row['stale']=row['stale'] or current!=row['results'].get('baseline_repository_id')
            for key in ('lease','lease_until','generation'):row.pop(key,None)
        return data

    def configure(self,identifier,keywords,enabled=False,interval_hours=24,project_focus=None):
        if identifier not in self.members():raise ValueError('项目尚未手动加入中控')
        if not isinstance(keywords,str) or len(keywords)>200 or type(enabled) is not bool or type(interval_hours) is not int or interval_hours not in (6,24,168):
            raise ValueError('检索词最多 200 字，周期请选择 6 小时、每天或每周')
        keywords=' '.join(keywords.split())
        if project_focus is not None and (not isinstance(project_focus,str) or len(project_focus)>1000):
            raise ValueError('项目定位最多 1000 字')
        if safe_text(keywords,200)!=keywords:
            raise ValueError('检索词含敏感信息，请移除后重试')
        if enabled and not keywords:raise ValueError('启用定时检索前请填写关键词')
        with self.store.connection() as db:
            previous=db.execute('SELECT * FROM control_discovery WHERE id=?',(identifier,)).fetchone()
            focus=safe_text(project_focus.strip(),1000) if project_focus is not None else (previous['project_focus'] if previous else '')
            unchanged=previous and previous['keywords']==keywords and previous['project_focus']==focus and bool(previous['enabled'])==enabled and previous['interval_hours']==interval_hours
            next_run=previous['next_run_at'] if unchanged else stamp() if enabled else None
            db.execute('INSERT INTO control_discovery(id,keywords,enabled,interval_hours,next_run_at,generation,project_focus) VALUES(?,?,?,?,?,1,?) '
                       'ON CONFLICT(id) DO UPDATE SET keywords=excluded.keywords,enabled=excluded.enabled,interval_hours=excluded.interval_hours,next_run_at=excluded.next_run_at,generation=control_discovery.generation+1,lease=NULL,lease_until=0,project_focus=excluded.project_focus',
                       (identifier,keywords,int(enabled),interval_hours,next_run,focus))
        return {'ok':True}

    def disable(self,identifier):
        with self.store.connection() as db:
            db.execute('UPDATE control_discovery SET enabled=0,next_run_at=NULL,generation=generation+1,lease=NULL,lease_until=0 WHERE id=?',(identifier,))

    def run(self,identifier,keywords=None,scheduled=False,project_focus=None):
        member=self.members().get(identifier)
        if member is None:raise ValueError('项目尚未手动加入中控')
        config=self.configs().get(identifier)
        if (keywords is not None and (not config or config['keywords']!=keywords)) or (project_focus is not None and (not config or config['project_focus']!=project_focus)):
            self.configure(identifier,keywords if keywords is not None else (config or {}).get('keywords',''),(config or {}).get('enabled',False),(config or {}).get('interval_hours',24),project_focus)
            config=self.configs()[identifier]
        if not config or not config['keywords']:raise ValueError('请先填写检索关键词')
        if scheduled and not config['enabled']:return {'accepted':False}
        token=uuid.uuid4().hex;clock=time.time()
        with self.lock:
            if identifier in self.jobs:return {'accepted':True,'running':True}
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT * FROM control_discovery WHERE id=?',(identifier,)).fetchone()
                if row['keywords']!=config['keywords'] or row['project_focus']!=config['project_focus']:
                    return {'accepted':False,'retry_after':1}
                budget=db.execute('SELECT last_started FROM control_discovery_budget WHERE id=1').fetchone()[0]
                if row['lease_until']>clock:return {'accepted':True,'running':True}
                if clock-budget<self.gap:return {'accepted':False,'retry_after':max(1,int(self.gap-clock+budget)+1)}
                db.execute('UPDATE control_discovery SET lease=?,lease_until=? WHERE id=?',(token,clock+240,identifier))
                generation=row['generation'];self.jobs.add(identifier)
        def search():
            try:
                with self.store.connection() as db:
                    current=db.execute('SELECT generation,lease,lease_until FROM control_discovery WHERE id=?',(identifier,)).fetchone()
                if not current or current['generation']!=generation or current['lease']!=token or current['lease_until']<time.time() or identifier not in self.members():return
                data,error=None,None
                try:
                    # Reserve the shared search budget at execution time, not queue time.
                    while not self.stop.is_set():
                        with self.store.connection() as db:
                            db.execute('BEGIN IMMEDIATE')
                            latest=db.execute('SELECT generation,lease FROM control_discovery WHERE id=?',(identifier,)).fetchone()
                            if not latest or latest['generation']!=generation or latest['lease']!=token:return
                            budget=db.execute('SELECT last_started FROM control_discovery_budget WHERE id=1').fetchone()[0]
                            delay=self.gap-(time.time()-budget)
                            if delay<=0:db.execute('UPDATE control_discovery_budget SET last_started=? WHERE id=1',(time.time(),))
                        if delay<=0:break
                        if self.stop.wait(min(delay,1)):return
                    if self.stop.is_set():return
                    data=self.github.search(config['keywords'])
                    current_repo=member.get('repository') or {}
                    data['repositories']=[r for r in data['repositories'] if r['github_id']!=current_repo.get('github_id')]
                    data['project_focus']=config['project_focus']
                    data['baseline_repository_id']=current_repo.get('github_id')
                    # Only a short public baseline and three public README samples; no local files or model.
                    baseline={}
                    profile=getattr(self.github,'public_profile',None)
                    if profile and current_repo:
                        try:
                            baseline=profile(current_repo['full_name'])
                            if baseline['github_id']!=current_repo['github_id']:baseline={}
                        except (ValueError,OSError,KeyError,TypeError):pass
                    data['baseline']={k:v for k,v in baseline.items() if k!='readme'}
                    for index,repository in enumerate(data['repositories']):
                        with self.store.connection() as db:
                            latest=db.execute('SELECT generation,lease FROM control_discovery WHERE id=?',(identifier,)).fetchone()
                        if self.stop.is_set() or identifier not in self.members() or not latest or latest['generation']!=generation or latest['lease']!=token:return
                        reference=dict(repository,readme_status='not_sampled',observed_at=data.get('observed_at'))
                        if index<3 and profile:
                            try:
                                source=profile(repository['full_name'])
                                if source['github_id']==repository['github_id']:reference.update(source)
                                else:reference['readme_status']='identity_changed'
                            except (ValueError,OSError,KeyError,TypeError):reference['readme_status']='unavailable'
                        repository['description']=safe_text(repository.get('description'),700)
                        repository['comparison']=compare(reference,baseline,config['project_focus'])
                    data['comparison_version']=1
                    with self.store.connection() as db:
                        previous_ids={r[0] for r in db.execute('SELECT github_id FROM control_discovery_seen WHERE id=?',(identifier,))}
                    data['new_count']=sum(r['github_id'] not in previous_ids for r in data['repositories'])
                except (ValueError,OSError,KeyError,TypeError):
                    error='外部项目检索暂不可用，已保留上次结果'
                next_run=(datetime.now(timezone.utc)+timedelta(hours=config['interval_hours'])).isoformat(timespec='seconds').replace('+00:00','Z') if config['enabled'] else None
                with self.store.connection() as db:
                    changed=db.execute('UPDATE control_discovery SET last_run_at=?,last_error=?,results=COALESCE(?,results),next_run_at=?,lease=NULL,lease_until=0 WHERE id=? AND generation=? AND lease=?',
                               (stamp(),error,json.dumps(data,ensure_ascii=False) if data is not None else None,next_run,identifier,generation,token))
                    if changed.rowcount and data:
                        db.executemany('INSERT OR IGNORE INTO control_discovery_seen(id,github_id) VALUES(?,?)',[(identifier,r['github_id']) for r in data['repositories']])
            finally:
                with self.lock:self.jobs.discard(identifier)
        self.executor.submit(search)
        return {'accepted':True,'running':True}

    def tick(self):
        members=self.members()
        with self.store.connection() as db:
            due=[r['id'] for r in db.execute('SELECT id FROM control_discovery WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at<=?) ORDER BY next_run_at LIMIT 30',(stamp(),))]
        for identifier in due:
            if identifier not in members:
                self.disable(identifier);continue
            result=self.run(identifier,scheduled=True)
            if result.get('accepted'):break

    def loop(self):
        while not self.stop.wait(15):
            try:self.tick()
            except (ValueError,OSError,sqlite3.Error):pass
