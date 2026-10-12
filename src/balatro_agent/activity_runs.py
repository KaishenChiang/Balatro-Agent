"""Per-run editing logs from already filtered activity; no game/model access."""
from datetime import datetime, timezone
import json
import os
import re
import uuid

from .file_io import open_file, replace_file
from .local_audit import canonical, make_dir, safe_path

ACTIVE_PHASES = {'blind_select','hand','round_eval','shop','pack','transition'}
PHASES = {'blind_select':'选择盲注','hand':'出牌','round_eval':'回合结算',
          'shop':'商店','pack':'卡包','transition':'过渡','terminal':'结算',
          'menu':'菜单','main_menu':'主菜单','unsupported':'状态未确认'}
ACTIONS = {'start_run':'开始新局','continue_run':'继续对局','select_blind':'选择盲注',
           'skip_blind':'跳过盲注','play':'出牌','discard':'弃牌','cash_out':'领取收入',
           'buy':'购买','buy_and_use':'购买并使用','sell':'出售','use':'使用',
           'reroll':'重掷商店','next_round':'离开商店','select_pack_card':'选择卡包牌',
           'skip_pack':'跳过卡包','close_menu':'关闭菜单','open_options':'打开选项',
           'main_menu':'返回主菜单','continue_endless':'继续无尽'}
STATES = {'COMPLETED':'完成','RUNNING':'执行中','UNKNOWN':'结果未确认',
          'AWAITING_INPUT':'等待原生提示','REJECTED':'拒绝'}


def clock(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('missing timezone')
    return result


def elapsed(milliseconds):
    sign = '-' if milliseconds < 0 else '+'
    seconds, ms = divmod(abs(milliseconds),1000)
    minutes, seconds = divmod(seconds,60)
    hours, minutes = divmod(minutes,60)
    return f'{sign}{hours:02}:{minutes:02}:{seconds:02}.{ms:03}'


def prose(data, field, limit=240):
    translated = data.get(field+'_i18n') or {}
    value = translated.get('zh-CN') or data.get(field) or ''
    return ' '.join(str(value).split())[:limit]


def message(row):
    """Fixed operation captions and submitted rationale, never invented advice."""
    data = row['data']; kind = row['kind']
    if kind == 'run':
        if data['event'] == 'start':
            label = '开局确认' if data['origin']=='confirmed_start' else '接续记录（开局时间未确认）'
            return f"{label} · 牌组：{data.get('deck') or '未确认'} · 注级：{data.get('stake') or '未确认'}"
        if data['event'] == 'end':
            return f"本局结束：{'胜利' if data['outcome']=='win' else '失败'} · 牌组：{data.get('deck') or '未确认'} · 注级：{data.get('stake') or '未确认'} · 底注：{data.get('ante') if data.get('ante') is not None else '未确认'} · 回合：{data.get('round') if data.get('round') is not None else '未确认'}"
        if data['event'] == 'resume':
            return '服务恢复记录；断连期间没有活动日志'
        return '记录中断：'+data['reason']+'（不计为正常败局）'
    if kind == 'observation':
        resources = data.get('resources') or {}
        return '状态：'+PHASES.get(data.get('phase'),'未确认')+' · '+' · '.join(
            label+': '+str(resources[key]) for key,label in [('ante','底注'),('round','回合'),('dollars','资金'),('chips','分数')]
            if resources.get(key) is not None)
    if kind == 'decision':
        target = data.get('target_name') or ''
        count = data.get('card_count')
        action = ACTIONS.get(data.get('action'),data.get('action') or '操作')
        return '决策：'+action+(f' {count}张' if count is not None else '')+(' '+target if target else '')+' · '+prose(data,'reason')
    if kind == 'action':
        return '操作：'+ACTIONS.get(data.get('action'),data.get('action') or '原生操作')+' · '+STATES.get(data.get('state'),data.get('status') or '状态未确认')
    if kind == 'plan':
        return '计划：'+prose(data,'objective')
    if kind == 'notes':
        return '心得：'+('已保存' if data.get('committed') else '结果未确认' if data.get('write_state')=='UNKNOWN' else '读取/核验')
    if kind == 'changes':
        return '公开变化：'+', '.join(data.get('changed') or [])
    if kind == 'calculation':
        return f"计算：{data.get('operation') or '未确认'} = {data.get('result') if data.get('result') is not None else '未确认'}"
    return '连接/提示：'+str(data.get('state') or data.get('status') or '已记录')


class RunActivity:
    """Stream two files per run; persist only the current recording cursor."""
    def __init__(self, root):
        self.root=root
        self.active=None
        self.problem=None
        self.restored=False
        try:
            path=safe_path(root,'active-run.json')
            if path.exists():
                with open_file(path,'rb') as stream:
                    data=stream.read(16385)
                if len(data)>16384: raise ValueError('record too large')
                self.active=json.loads(data)
                self._validate(self.active)
                self.restored=self.active['status']=='recording'
        except Exception:
            self.active=None; self.problem='storage_unavailable'

    @staticmethod
    def _validate(row):
        if (not isinstance(row,dict) or set(row)!={'schema','stem','game_session','profile','origin','started_utc',
                'status','outcome','deck','stake','round','cursor','pending'}
                or row['schema']!='activity-run-v1'
                or not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{12}',row['stem'])
                or not re.fullmatch(r'[0-9a-f]{16}',row['game_session'])
                or type(row['profile']) is not int or row['profile'] not in (1,2,3)
                or row['origin'] not in ('confirmed_start','partial_continue','partial_observation')
                or row['status'] not in ('recording','completed','interrupted')
                or row['outcome'] not in (None,'win','loss')
                or (row['status']=='completed') != (row['outcome'] in ('win','loss'))
                or type(row['cursor']) is not int or row['cursor']<0
                or not isinstance(row['pending'],list) or len(row['pending'])>4
                or any(not isinstance(v,str) or len(v)>80 for v in row['pending'])
                or any(v is not None and (not isinstance(v,str) or len(v)>80) for v in (row['deck'],row['stake']))):
            raise ValueError('invalid run record')
        clock(row['started_utc'])
        if row['round'] is not None and (type(row['round']) not in (int,float) or not 0<=row['round']<=100000):
            raise ValueError('invalid round')

    def _save(self):
        self._validate(self.active)
        make_dir(self.root)
        path=safe_path(self.root,'active-run.json')
        temporary=safe_path(self.root,'.run-'+uuid.uuid4().hex+'.tmp')
        try:
            with open_file(temporary,'xb') as stream:
                stream.write(canonical(self.active).encode('utf-8'));stream.flush();os.fsync(stream.fileno())
            replace_file(temporary,path)
        finally:
            if temporary.exists(): safe_path(self.root,temporary.name).unlink()

    def _row(self,data):
        return {'schema':'activity-run-marker-v1','session':None,'sequence':None,
                'utc':datetime.now(timezone.utc).isoformat(),'kind':'run','tool':'activity_log','data':data}

    def observe(self, observation, start=None):
        """Boundaries use delivered public session/profile/round, never a save."""
        if self.problem: return
        oid=observation.get('observation_id','').split('-')
        if len(oid)!=3 or not re.fullmatch('[0-9a-f]{16}',oid[1]) or not oid[2].isdigit(): return
        profile=observation.get('profile')
        if type(profile) is not int or profile not in (1,2,3): return
        phase=observation.get('phase'); round_=(observation.get('resources') or {}).get('round')
        cursor=int(oid[2]); active=self.active if self.active and self.active['status']!='interrupted' else None
        if active and active['game_session']==oid[1] and cursor<active['cursor']: return False
        same=active and active['game_session']==oid[1] and active['profile']==profile
        reset=active and (not same or phase=='main_menu'
                         or (round_ is not None and active['round'] is not None and round_<active['round']))
        if start=='start_run' or reset:
            if active and active['status']=='recording':
                self.append(self._row({'event':'interrupted','reason':'新局、档位或会话边界变化'}))
                active['status']='interrupted';self._save()
            active=None
        needs_start=(start in ('start_run','continue_run') and not active) or (not active and phase in ACTIVE_PHASES)
        if needs_start:
            now=datetime.now(timezone.utc)
            self.active={'schema':'activity-run-v1','stem':now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12],
                'game_session':oid[1],'profile':profile,
                'origin':'confirmed_start' if start=='start_run' else 'partial_continue' if start=='continue_run' else 'partial_observation',
                'started_utc':now.isoformat(),'status':'recording','outcome':None,
                'deck':(observation.get('setup') or {}).get('deck_name'),
                'stake':(observation.get('setup') or {}).get('stake_name'),
                'round':round_,'cursor':cursor,'pending':[]}
            folder=safe_path(self.root,'by-run')
            if any(safe_path(folder,self.active['stem']+suffix).exists() for suffix in ('.jsonl','.txt')):
                raise ValueError('preserve existing run files')
            self._save()
            self.append(self._row({'event':'start',**{key:self.active[key] for key in ('origin','deck','stake','started_utc')}}))
        elif active:
            active['cursor']=cursor
            if round_ is not None: active['round']=round_
            for field,source in [('deck','deck_name'),('stake','stake_name')]:
                value=(observation.get('setup') or {}).get(source)
                if value is not None: active[field]=value
            self._save()
            if self.restored and active['status']=='recording':
                self.append(self._row({'event':'resume'}))
        self.restored=False
        return True

    def append(self,row):
        if self.problem or not self.active or self.active['status']=='interrupted': return
        data=row['data']
        if data.get('historical'): return
        # After settlement retain only the same run's experience updates.
        if self.active['status']=='completed' and row['kind'] not in ('notes',): return
        milliseconds=round((clock(row['utc'])-clock(self.active['started_utc'])).total_seconds()*1000)
        value={**row,'run_log':{'id':self.active['stem'],'elapsed_ms':milliseconds,
                             'origin':self.active['origin']}}
        folder=safe_path(self.root,'by-run');make_dir(folder)
        json_path=safe_path(folder,self.active['stem']+'.jsonl')
        timeline_path=safe_path(folder,self.active['stem']+'.txt')
        first=not timeline_path.exists()
        with open_file(json_path,'a',encoding='utf-8') as stream:
            stream.write(canonical(value)+'\n')
            if row['kind']=='run': stream.flush();os.fsync(stream.fileno())
        with open_file(timeline_path,'a',encoding='utf-8') as stream:
            if first:
                stream.write('剪辑时间轴：实际时间（UTC偏移） | 从记录起点经过时间 | 活动\n'
                    '录像需先对齐一个共同事件；这里不是录像时间码。接续记录不代表完整对局时长。\n\n')
            actual=clock(row['utc']).astimezone().isoformat(timespec='milliseconds')
            stream.write(actual+' | '+elapsed(milliseconds)+' | '+message(row)+'\n')
            if row['kind']=='run': stream.flush();os.fsync(stream.fileno())
        if row['kind']=='action' and data.get('action_id'):
            pending=set(self.active['pending']);identifier=data['action_id']
            if data.get('state') in ('UNKNOWN','RUNNING','AWAITING_INPUT'): pending.add(identifier)
            elif data.get('state') in ('COMPLETED','REJECTED'): pending.discard(identifier)
            self.active['pending']=sorted(pending)
            self._save()

    def finish(self,observation):
        if self.problem or not self.active or self.active['status']!='recording' or self.active['pending']: return
        oid=observation.get('observation_id','').split('-')
        if (len(oid)!=3 or oid[1]!=self.active['game_session'] or not oid[2].isdigit()
                or int(oid[2])<self.active['cursor'] or observation.get('profile')!=self.active['profile']): return
        if not ((observation.get('phase')=='terminal' or observation.get('underlying_phase')=='terminal')
                and observation.get('ready') is True
                and observation.get('outcome') in ('win','loss')): return
        resources=observation.get('resources') or {}
        self.append(self._row({'event':'end','outcome':observation['outcome'],
                              'ante':resources.get('ante'),'round':resources.get('round'),
                              'deck':self.active['deck'],'stake':self.active['stake']}))
        self.active.update(status='completed',outcome=observation['outcome'])
        self._save()

    def status(self):
        if self.problem: return {'status':self.problem}
        if not self.active: return {'status':'not_started'}
        return {'status':self.active['status'],'origin':self.active['origin'],
                'outcome':self.active['outcome'],'relative_to':'configured log directory',
                'events':'activity/by-run/'+self.active['stem']+'.jsonl',
                'timeline':'activity/by-run/'+self.active['stem']+'.txt'}
