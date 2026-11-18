#!/usr/bin/env python3
"""Render evidence-linked Chinese visa explainers. Local Pillow + ffmpeg + macOS say.

python scripts/render_media.py --keyframes
python scripts/render_media.py --render all
Requires Pillow, numpy, imageio-ffmpeg. No source data mutations or network calls.
"""
from __future__ import annotations
import argparse, collections, csv, functools, hashlib, json, math, os, re, subprocess, sys, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio_ffmpeg
from verify_media_data import verify_media_data
ROOT=Path(__file__).resolve().parents[1]; MEDIA=ROOT/'media'
for folder in ['audio','keyframes','covers','subtitles','exports','evidence']:(MEDIA/folder).mkdir(exist_ok=True)
FFMPEG=os.environ.get('FFMPEG_BINARY') or imageio_ffmpeg.get_ffmpeg_exe()
FONT=Path(os.environ.get('VISA_CJK_FONT','/System/Library/Fonts/STHeiti Medium.ttc'))
FONT_REG=Path('/System/Library/Fonts/STHeiti Light.ttc')
BOLD=Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')
PALETTE={'paper':'#F5F1E8','ink':'#152B3A','teal':'#087E78','coral':'#EF7257','muted':'#657779','line':'#D9DFD7','white':'#FFFEFA','soft':'#E5EDE4'}
FPS=24
MEDIA_CLAIM_LOCK={'fee_us_b_2024': {'statement': '2024标准B类申请费USD185；拒签不退。185×7.1957=1331.2045CNY，约1331元。',
                   'scope': '历史2024费率；不包括额外服务／适用互惠费。',
                   'supporting_source_ids': ['us_fees2024_cfr', 'us_fee_schedule', 'fx_fed_g5a_20260105']},
 'fee_jp_issue_only': {'statement': '日本政府签证费在签发时收取；未签发不收政府费；指定代办手续费另外收取。',
                       'scope': '政府签证费与代办费不同。',
                       'supporting_source_ids': ['jp_fee_old']},
 'bill_uk_student_2024_one_year': {'statement': '2024学生申请费GBP490；学生IHS按一个计费年GBP776演示，总额GBP1266。',
                                   'scope': '一个计费年示例；实际按签证有效期，可能有半年计费或附加月数。2024年2月6日起IHS费率。',
                                   'supporting_source_ids': ['uk_fees_apr2024', 'uk_ihs', 'uk_ihs_guidance']},
 'fin_us_fy2024': {'observation_id': 'us_2024_world_all_mrv_including_bcc_mrv_receipts_actual',
                   'statement': '美国FY2024 MRV实收USD2561million=25.61亿美元。按2024年均汇率7.1957，约CNY184.3亿元。',
                   'scope': '2023-10-01—2024-09-30；含BCC边境通行卡；非所有移民收费，非利润；人民币值为全年平均汇率换算。',
                   'supporting_source_ids': ['us_omb2026', 'fx_fed_g5a_20260105']},
 'policy_tha_2024': {'statement': '2024年合资格中国普通护照短期赴泰旅客免办签证，政府签证费0。',
                     'scope': '资格／目的／停留期限遵循各阶段政策；不代表一切赴泰活动或旅行花费0。',
                     'supporting_source_ids': ['th_waiver_temporary', 'th_waiver_mutual']},
 'policy_sgp_2024': {'statement': '2024-02-09起，合资格中国普通护照持有人短期赴新免签，政府签证费0。',
                     'scope': '30日以内合资格短访；入境审核及其他费用另外。',
                     'supporting_source_ids': ['sg_waiver']},
 'waiver_sgp_reuse_demo': {'statement': '旧／假设收费SGD30每张；假设一张签证覆盖1、2、4趟且无其他收费，每趟分摊SGD30、15、7.5。',
                           'scope': '纯条件情景，非实际节省估计；免签后合资格短访政府签证费0。',
                           'supporting_source_ids': ['sg_fee', 'sg_waiver']}}
# Validate the locked narrative against final master records before any media generation.
_, CLAIMS = verify_media_data(ROOT, MEDIA_CLAIM_LOCK, require_baseline=True)

def S(key,duration,visual,heading,tag,narration,claims=(),note='',**extra):
    return dict(key=key,duration=duration,visual=visual,heading=heading,tag=tag,narration=narration,claim_ids=list(claims),note=note,**extra)
FLAGSHIP=[
 S('hook',5,'hook','拒签了，\n钱会退吗？','一张签证账单，先看收费时点',['签证被拒了，钱会退吗？','先看这笔钱，在什么时候收。']),
 S('us',10,'us','约1,331元','美国 · 2024年标准B类申请费',['美国2024年标准B类申请费185美元。','按2024年均汇率，约1331元人民币，拒签不退。'],['fee_us_b_2024'],'USD185 × 7.1957；人民币按2024年均汇率换算'),
 S('jp',9,'japan','签发时，\n才收政府费','日本 · 先分清政府费与代办费',['日本的政府签证费，在签发时收。','没签发，不收政府费；代办手续费另外算。'],['fee_jp_issue_only'],'政府签证费规则；代办手续费由具体渠道确定'),
 S('uk',12,'bill','£1,266','英国学生 · 2024年一个计费年示例',['英国学生申请费490英镑，加一个计费年的IHS776英镑。','合计1266英镑，实际按签证有效期计费。'],['bill_uk_student_2024_one_year'],'一个计费年示例；IHS实际按签证有效期计费'),
 S('revenue',12,'revenue','约184.3亿元','美国 · FY2024 MRV实际收款',['再看总账：美国2024财年，MRV实收25.61亿美元。','约184.3亿元人民币，含边境通行卡；收入不等于利润。'],['fin_us_fy2024'],'2023-10—2024-09；含BCC；按2024年均汇率换算'),
 S('waiver',10,'waiver','合资格短访\n政府签证费0','中国普通护照 · 历史2024政策',['合资格短访，泰国在2024年免签。','新加坡从2024年2月9日起免签，政府签证费是零。'],['policy_tha_2024','policy_sgp_2024'],'免签资格、旅行目的与停留期限适用各地政策'),
 S('reuse',8,'reuse','一张签证，\n可以对应多趟旅行','为什么游客次数 × 旧价，算不出实际节省',['一张签证，可能对应多趟旅行。','游客次数乘旧签证价，算不出实际节省。'],['waiver_sgp_reuse_demo'],'演示：假设SGD30一张签证可复用；非实际节省估计'),
 S('close',9,'close','先拆账单，\n再看钱怎么流','签证账单，钱到底交给谁？',['先分清政府费、附加费和代办费。','打开交互页，点每个数字，就能看到来源。'],note='研究截止2026-11-15；历史费率与最新政策分开查看')]
REFUND=[
 S('refund_hook',5,'hook','拒签以后，\n这笔钱退吗？','拒签账单 · 美国与日本',['拒签以后，钱退不退？','先看收费时点。']),
 S('refund_us',9,'us','美国：拒签不退','2024年 · 标准B类申请费',['美国2024年标准B类申请费185美元。','这笔申请费，拒签也不退。'],['fee_us_b_2024'],'历史2024费率；约CNY1331按2024年均汇率换算'),
 S('refund_jp',9,'japan','日本：未签发\n不收政府费','政府签证费与代办手续费分开',['日本政府签证费，在签发时收。','没签发就不收政府费，代办手续费另算。'],['fee_jp_issue_only'],'代办费退款看具体渠道规则'),
 S('refund_close',5,'close','付钱前，\n先看收的是什么','收费时点，决定了退款规则',['付钱前，先看收的是什么。','到交互页查看原文与完整账单。'])]
UK=[
 S('uk_hook',5,'hook','英国学生签证，\n只看申请费够吗？','拆一张2024年的账单',['英国学生签证，只看申请费够吗？']),
 S('uk_base',7,'bill','£490','2024年 · 学生签证申请费',['2024年，英国学生签证申请费490英镑。'],['bill_uk_student_2024_one_year'],'历史2024费率；后续年份另查',bill_stage=1),
 S('uk_ihs',8,'bill','再加 £776','学生IHS · 一个计费年示例',['学生IHS，再按一个计费年776英镑来演示。'],['bill_uk_student_2024_one_year'],'一个计费年示例；实际按签证有效期',bill_stage=2),
 S('uk_total',10,'bill','合计 £1,266','2024年 · 一个计费年示例',['合计1266英镑。','实际IHS按签证有效期计费，可能还有半年计费。'],['bill_uk_student_2024_one_year'],'一个计费年示例；实际按签证有效期',bill_stage=3)]
WAIVER=[
 S('waiver_hook',6,'waiver','免签，\n究竟省了多少？','从新加坡的一张旧签证说起',['免签，究竟省了多少？','先从一张签证看起。'],['policy_sgp_2024'],'2024-02-09起，合资格中国普通护照短访政府签证费0'),
 S('reuse_one',7,'reuse','一张30新元','纯条件情景 · 假设一张签证用于1趟',['假设旧签证每张30新元，只用一趟。','每趟分摊30新元。'],['waiver_sgp_reuse_demo'],'假设SGD30一张；无其他费用；非实际节省估计',reuse_n=1),
 S('reuse_two',7,'reuse','两趟，每趟15','纯条件情景 · 假设同一张签证可复用',['如果同一张签证，用了两趟。','每趟分摊，就是15新元。'],['waiver_sgp_reuse_demo'],'复用必须满足有效期、入境次数等条件',reuse_n=2),
 S('reuse_four',7,'reuse','四趟，每趟7.5','纯条件情景 · 假设同一张签证可复用',['假设能用四趟，每趟分摊7点5新元。','旅行次数，并不等于新办签证数。'],['waiver_sgp_reuse_demo'],'假设可用于四趟；非实际办理次数或节省估计',reuse_n=4),
 S('waiver_close',7,'waiver','免签后，\n合资格签证费0','新加坡 · 2024-02-09起',['免签后，合资格短访政府签证费是零。','实际省下多少，还要看原本会新办几张签证。'],['policy_sgp_2024','waiver_sgp_reuse_demo'],'资格与停留期适用政策；其他旅行支出另计')]
VIDEOS={
 'flagship_vertical':dict(title='签证账单，钱到底交给谁？',size=(1080,1920),scenes=FLAGSHIP),
 'flagship_horizontal':dict(title='签证账单，钱到底交给谁？',size=(1920,1080),scenes=FLAGSHIP),
 'cut_refund':dict(title='拒签了，为什么有的费用不退？',size=(1080,1920),scenes=REFUND),
 'cut_uk_bill':dict(title='英国学生签证：申请费之外，还有这一笔',size=(1080,1920),scenes=UK),
 'cut_waiver':dict(title='免签究竟省多少？先别拿游客次数乘旧价',size=(1080,1920),scenes=WAIVER)}
for _spec in VIDEOS.values():
    for _scene in _spec['scenes']:
        if _scene['visual']=='bill':
            _scene['note']='2024-02-06起IHS费率；一个计费年示例；实际按签证有效期'
SPOKEN={'2024':'二零二四','2026':'二零二六','185':'一百八十五','1331':'一千三百三十一','490':'四百九十','776':'七百七十六','1266':'一千二百六十六','25.61':'二十五点六一','184.3':'一百八十四点三','MRV':'机器可读签证费用','IHS':'医疗附加费'}

def run(cmd,**kw):return subprocess.run([str(x) for x in cmd],check=True,**kw)
def dur_wav(path):
    with wave.open(str(path),'rb') as w:return w.getnframes()/w.getframerate()
def speak_text(text):
    for a,b in sorted(SPOKEN.items(),key=lambda x:-len(x[0])):text=text.replace(a,b)
    return text

def audio_for(video_id,spec):
    """One synthesized sentence per subtitle cue, measured and scheduled without clipping."""
    scenes=[];global_cues=[];cursor=0;sr=44100
    audio_all=[]
    for scene in spec['scenes']:
        chunks=[];raw_durs=[]
        for text in scene['narration']:
            spoken=speak_text(text);h=hashlib.sha256(('Tingting205'+spoken).encode()).hexdigest()[:16]
            aiff=MEDIA/f'audio/speech_{h}.aiff';wav=MEDIA/f'audio/speech_{h}.wav'
            if not wav.exists():
                run(['say','-v','Tingting','-r','205','-o',aiff,spoken],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                run([FFMPEG,'-v','error','-y','-i',aiff,'-ar',sr,'-ac','1','-c:a','pcm_s16le',wav])
            raw_durs.append(dur_wav(wav));chunks.append(wav)
        available=scene['duration']-.65-.12*(len(chunks)-1)
        tempo=max(1,sum(raw_durs)/available)
        assert tempo<1.5,(video_id,scene['key'],tempo)
        local=.25;audio=np.zeros(int(scene['duration']*sr),dtype=np.float32)
        cues=[]
        for text,wav,duration in zip(scene['narration'],chunks,raw_durs):
            processed=MEDIA/f'audio/{video_id}_{scene["key"]}_{len(cues)}.wav'
            run([FFMPEG,'-v','error','-y','-i',wav,'-af',f'atempo={tempo:.7f},afade=t=in:st=0:d=0.025,afade=t=out:st={max(.03,duration/tempo-.04):.6f}:d=0.04','-ar',sr,'-ac','1',processed])
            with wave.open(str(processed),'rb') as w:buf=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
            start=int(local*sr);end=start+len(buf);assert end<=len(audio),(scene['key'],end,len(audio))
            audio[start:end]+=buf
            c=dict(start=cursor+local,end=cursor+local+len(buf)/sr,text=text,scene=scene['key'],claim_ids=scene['claim_ids'])
            cues.append(c);global_cues.append(c);local+=len(buf)/sr+.12
        audio_all.append(audio);scenes.append(dict(scene,start=cursor,end=cursor+scene['duration'],tempo_factor=round(tempo,5),cues=cues))
        cursor+=scene['duration']
    voice=np.concatenate(audio_all)
    # Quiet original sound design: gentle pitched pips at scene changes, no third-party music.
    for scene in scenes:
        start=int(scene['start']*sr);n=int(.12*sr);t=np.arange(n)/sr
        pip=.025*np.sin(2*math.pi*660*t)*np.sin(math.pi*t/.12)**2
        voice[start:start+n]+=pip
    peak=float(np.max(np.abs(voice)));gain=min(.88/max(peak,.01),1.35);voice*=gain
    wav=MEDIA/f'audio/{video_id}.wav'
    with wave.open(str(wav),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes((np.clip(voice,-1,1)*32767).astype('<i2').tobytes())
    return scenes,global_cues,dict(duration=cursor,sample_rate=sr,peak_dbfs=20*math.log10(max(np.max(np.abs(voice)),1e-12)),rms_dbfs=20*math.log10(max(float(np.sqrt(np.mean(voice**2))),1e-12)),voice='macOS Tingting',max_tempo_factor=max(x['tempo_factor'] for x in scenes))

@functools.lru_cache(maxsize=128)
def font(size,latin=False,regular=False):return ImageFont.truetype(str(BOLD if latin else FONT_REG if regular else FONT),max(8,round(size)))
def color(k):return PALETTE.get(k,k)
def wrap(text,face,width):
    result=[]
    for paragraph in text.split('\n'):
        line=''
        for ch in paragraph:
            if line and face.getlength(line+ch)>width:result.append(line);line=ch
            else:line+=ch
        result.append(line)
    return result

def txt(d,xy,text,size,fill='ink',width=None,spacing=1.25,latin=False,regular=False):
    face=font(size,latin,regular);lines=wrap(text,face,width) if width else text.split('\n');x,y=xy
    for line in lines:
        d.text((round(x),round(y)),line,font=face,fill=color(fill),stroke_width=0)
        y+=size*spacing
    return y

def center(d,x,y,text,size,fill='ink',latin=False):
    face=font(size,latin);d.text((x-face.getlength(text)/2,y),text,font=face,fill=color(fill))
def pill(d,box,text,fill='teal',textfill='white',size=30):
    d.rounded_rectangle(box,radius=(box[3]-box[1])/2,fill=color(fill));center(d,(box[0]+box[2])/2,box[1]+(box[3]-box[1]-size)/2-2,text,size,textfill)
def ease(x):x=max(0,min(1,x));return 1-(1-x)**3

def base(spec):
    w,h=spec['size'];im=Image.new('RGB',(w,h),color('paper'));d=ImageDraw.Draw(im)
    for y in range(0,h,34):
        for x in range(0,w,34):d.ellipse((x,y,x+1,y+1),fill='#E6E4DA')
    if h>w:
        txt(d,(90,110),'VISA / MONEY / PEOPLE',26,'teal',latin=True)
        txt(d,(90,154),'签证账单研究',30,'muted');d.line((90,222,950,222),fill=color('line'),width=2)
        d.rounded_rectangle((632,145,950,193),radius=12,fill=color('white'),outline=color('line'),width=1)
        txt(d,(651,157),'AI配音 · 程序动画',24,'muted')
        d.arc((720,-160,1210,330),0,360,fill=color('line'),width=2)
    else:
        txt(d,(84,55),'VISA / MONEY / PEOPLE',24,'teal',latin=True);txt(d,(1350,52),'签证账单研究  ·  2024',24,'muted')
        txt(d,(1350,84),'AI配音 · 程序动画',21,'muted')
        d.line((84,112,w-84,112),fill=color('line'),width=2)
    return im

@functools.lru_cache(maxsize=80)
def layout(video_id,scene_key):
    spec=VIDEOS[video_id];scene=next(s for s in spec['scenes'] if s['key']==scene_key);w,h=spec['size'];vertical=h>w
    im=base(spec);d=ImageDraw.Draw(im)
    if vertical:
        txt(d,(90,268),scene['tag'],30,'teal',width=860)
        txt(d,(84,350),scene['heading'],96 if len(scene['heading'])<14 else 86,'ink',width=875,spacing=1.18)
        box=(90,665,950,1325)
        txt(d,(92,1380),scene['note'],30,'muted',width=850,spacing=1.32)
        txt(d,(90,1812),'历史费率 / 规则对照 / 费用情景',24,'muted')
    else:
        txt(d,(86,183),scene['tag'],28,'teal',width=690)
        txt(d,(82,275),scene['heading'],88 if len(scene['heading'])<16 else 72,'ink',width=705,spacing=1.18)
        box=(870,193,1834,770)
        txt(d,(88,725),scene['note'],25,'muted',width=690,spacing=1.3)
        txt(d,(84,1016),'历史费率 / 规则对照 / 费用情景',21,'muted')
    d.rounded_rectangle(box,radius=34,fill=color('white'),outline=color('line'),width=2)
    return im,box

def graphic(im,box,scene,p,t,vertical):
    """Animated diagram in normalized 860x660 coordinates; composited into each aspect ratio."""
    gw,gh=860,660;g=Image.new('RGB',(gw,gh),color('white'));d=ImageDraw.Draw(g);kind=scene['visual'];a=ease(p*2.8)
    def text(x,y,s,sz=34,c='ink',**kw):return txt(d,(x,y),s,sz,c,**kw)
    if kind=='hook':
        d.rounded_rectangle((235,58,625,477),radius=28,fill=color('soft'))
        text(278,99,'VISA',68,'teal',latin=True);d.line((278,193,578,193),fill=color('line'),width=3)
        for y,width in [(246,236),(301,174),(356,208)]:d.rounded_rectangle((278,y,278+width*a,y+12),radius=6,fill=color('line'))
        d.ellipse((570,380,730,540),fill=color('coral'));center(d,650,384,'?',116,'white',True)
        pill(d,(60,545,407,610),'申请时收费','teal',size=34);pill(d,(450,545,797,610),'签发时收费','ink',size=34)
    elif kind=='us':
        text(55,42,'政府申请费',34,'muted');text(50,100,'USD 185',92,'ink',latin=True)
        pill(d,(565,60,800,125),'2024','soft','teal',32)
        xs=[153,430,707];labels=['递交申请','审理','作出决定']
        for i in range(2):
            d.line((xs[i]+53,330,xs[i+1]-53,330),fill=color('line'),width=7)
            q=(t*.23+i*.31)%1;cx=xs[i]+53+q*(xs[i+1]-xs[i]-106);d.ellipse((cx-8,322,cx+8,338),fill=color('teal'))
        for i,(x,label) in enumerate(zip(xs,labels)):
            d.ellipse((x-51,279,x+51,381),fill=color('coral' if i==0 else 'soft'))
            center(d,x,299,str(i+1),43,'white' if i==0 else 'teal',True);center(d,x,416,label,32)
        pill(d,(77,533,783,609),'拒签：申请费不退','coral',size=42)
    elif kind=='japan':
        text(50,40,'日本政府签证费',35,'muted')
        for y,left,right,c in [(145,'签证签发','收政府费','teal'),(322,'未签发','政府费 0','ink')]:
            d.rounded_rectangle((50,y,810,y+125),radius=23,fill=color('soft'))
            text(87,y+38,left,42);text(465,y+31,right,49,c)
            d.line((355,y+63,416,y+63),fill=color(c),width=5);d.polygon([(416,y+63),(400,y+53),(400,y+73)],fill=color(c))
        d.line((60,500,800,500),fill=color('line'),width=2);text(77,544,'＋ 代办手续费：另计',43,'coral')
    elif kind=='bill':
        stage=scene.get('bill_stage',3);text(52,34,'2024 · 一个计费年示例',31,'muted')
        y1,y2=129,286
        for y,label,amt,c,show in [(y1,'申请费',490,'teal',True),(y2,'学生IHS / 1计费年',776,'coral',stage>=2)]:
            if not show:continue
            text(55,y,label,35);text(600,y-4,f'£{amt}',44,c,latin=True)
            d.rounded_rectangle((55,y+65,55+745*amt/776*a,y+106),radius=12,fill=color(c))
        if stage>=3:
            d.line((55,455,805,455),fill=color('line'),width=2);text(55,493,'合计',37);text(365,477,'£1,266',77,'ink',latin=True)
        text(55,601,'实际IHS按签证有效期计费',29,'muted')
    elif kind=='revenue':
        text(48,36,'MRV 实际收款',35,'muted');text(45,97,'USD 25.61 亿',76,'ink')
        d.line((77,337,780,337),fill=color('line'),width=15)
        for i in range(13):
            q=(t*.16+i/13)%1;x=77+703*q;d.ellipse((x-8,329,x+8,345),fill=color('teal'))
        d.ellipse((40,280,154,394),fill=color('soft'));center(d,97,313,'缴费',30,'teal')
        d.rounded_rectangle((635,266,815,407),radius=20,fill=color('teal'));center(d,725,310,'政府',38,'white')
        text(52,455,'FY2024',48,'teal',latin=True);text(52,516,'2023-10 至 2024-09',33)
        pill(d,(50,580,807,630),'含边境通行卡 BCC · 收入 ≠ 利润','soft','ink',29)
    elif kind=='waiver':
        text(53,35,'合资格中国普通护照短期访问',30,'muted')
        text(56,111,'0',205,'teal',latin=True);text(218,245,'政府签证费',46,'ink')
        for y,name,date in [(410,'泰国','2024年'),(510,'新加坡','2024-02-09 起')]:
            d.rounded_rectangle((55,y,805,y+83),radius=20,fill=color('soft'));text(86,y+23,name,37);text(377,y+28,date,31,'teal')
        text(57,611,'资格 / 目的 / 停留期，按各地政策',25,'muted')
    elif kind=='reuse':
        text(49,32,'纯条件情景：30新元 / 张',33,'coral')
        ns=[1,2,4];values=['30','15','7.5'];active=scene.get('reuse_n')
        for i,(n,value) in enumerate(zip(ns,values)):
            x=54+i*267;focus=active is None or n==active;c='teal' if focus else 'line'
            d.rounded_rectangle((x,143,x+232,481),radius=22,fill=color('soft' if focus else 'paper'))
            center(d,x+116,183,f'{n}趟',45,'ink');center(d,x+116,291,value,72,c,True);center(d,x+116,399,'新元 / 趟',27,'muted')
        text(58,540,'假设同一张签证覆盖这些行程',33)
        text(58,601,'签证复用情景 ≠ 真实节省估计',29,'coral')
    elif kind=='close':
        nodes=[(430,100,'政府费','teal'),(160,355,'附加费','coral'),(700,355,'代办费','ink')]
        for x,y,label,c in nodes:
            d.line((430,510,x,y),fill=color('line'),width=4)
            q=(t*.2)%1;cx=430+(x-430)*q;cy=510+(y-510)*q;d.ellipse((cx-7,cy-7,cx+7,cy+7),fill=color(c))
            d.ellipse((x-86,y-70,x+86,y+102),fill=color(c));center(d,x,y-5,label,38,'white')
        pill(d,(205,505,655,604),'点数字，看来源','soft','teal',41)
    sz=(box[2]-box[0]-4,box[3]-box[1]-4);fitted=ImageOps.contain(g,sz,Image.Resampling.LANCZOS)
    im.paste(fitted,(box[0]+2+(sz[0]-fitted.width)//2,box[1]+2+(sz[1]-fitted.height)//2))
    return im

def frame(video_id,scene,local_t,global_t,total,cues,static=False):
    spec=VIDEOS[video_id];w,h=spec['size'];vertical=h>w
    cached,box=layout(video_id,scene['key']);im=cached.copy()
    graphic(im,box,scene,local_t/scene['duration'],global_t,vertical)
    d=ImageDraw.Draw(im)
    labels={'us':'美国22 CFR费表；美联储年均汇率','japan':'日本外务省签证收费说明','bill':'英国Home Office费表；IHS计费规则',
        'revenue':'美国OMB预算附录实收表；美联储汇率','waiver':'新加坡ICA；中泰免签政策公告','reuse':'新加坡ICA费率；签证复用条件情景'}
    if scene['visual'] in labels:
        txt(d,(90,1768) if vertical else (84,978),'来源：'+labels[scene['visual']],24 if vertical else 21,'muted',width=850 if vertical else 1700)
    # Progress and a restrained entrance slide for the diagram; no flashing.
    d.rectangle((0,h-7,int(w*global_t/total),h),fill=color('teal'))
    if static:
        text=scene['narration'][0]
    else:
        text=next((c['text'] for c in cues if c['start']<=global_t<=c['end']+.12),'')
    if text:
        size=42 if vertical else 38;width=850 if vertical else 1540;face=font(size)
        lines=wrap(text,face,width)
        if len(lines)>2:size=36 if vertical else 34;face=font(size);lines=wrap(text,face,width)
        x0,x1=(72,970) if vertical else (160,w-160);y0=(1555 if vertical else 864)
        height=len(lines)*size*1.3+36
        d.rounded_rectangle((x0,y0,x1,y0+height),radius=18,fill=color('ink'))
        for i,line in enumerate(lines):center(d,(x0+x1)/2,y0+18+i*size*1.3,line,size,'white')
    # A soft paper veil only at scene boundaries gives clean transitions without hiding long data reads.
    if not static and local_t<.20:
        im=Image.blend(Image.new('RGB',(w,h),color('paper')),im,ease(local_t/.20))
    return im

def timestamp(sec):
    ms=round(sec*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
def save_srt(video_id,cues):
    out='\n\n'.join(f'{i+1}\n{timestamp(c["start"])} --> {timestamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))+'\n'
    (MEDIA/f'subtitles/{video_id}.srt').write_text(out)

def evidence():
    (MEDIA/'evidence/claims_snapshot.json').write_text(json.dumps(CLAIMS,ensure_ascii=False,indent=2)+'\n')
    (MEDIA/'storyboard.json').write_text(json.dumps(VIDEOS,ensure_ascii=False,indent=2))

def keyframes():
    evidence();contact=[]
    for video_id,spec in VIDEOS.items():
        total=sum(s['duration'] for s in spec['scenes']);cursor=0
        for idx,scene in enumerate(spec['scenes']):
            im=frame(video_id,scene,scene['duration']*.6,cursor+scene['duration']*.6,total,[],True)
            im.save(MEDIA/f'keyframes/{video_id}_{idx+1:02d}_{scene["key"]}.png')
            if video_id in ['flagship_vertical','flagship_horizontal']:contact.append((video_id,idx,im.copy()))
            cursor+=scene['duration']
        cover_scene=dict(spec['scenes'][0]);cover_scene['heading']=spec['title']
        # Standalone editorial cover with controlled title wrapping, built from the same palette.
        w,h=spec['size'];im=base(spec);d=ImageDraw.Draw(im);vertical=h>w
        covers={'flagship_vertical':'签证账单，\n钱到底交给谁？','flagship_horizontal':'签证账单，钱到底交给谁？',
            'cut_refund':'拒签了，\n钱退不退？','cut_uk_bill':'英国学生签证\n申请费之外，\n还有这一笔','cut_waiver':'免签，\n究竟省多少？'}
        txt(d,(90,315 if vertical else 220),covers[video_id],110 if vertical else 112,'ink',width=855 if vertical else 1500,spacing=1.24)
        txt(d,(90,925 if vertical else 650),'政府费 · 附加费 · 代办费',40,'teal',width=w-180)
        txt(d,(90,1630 if vertical else 940),'数字有出处，账单拆开看',34,'muted')
        d.rounded_rectangle((90,1100 if vertical else 800,w-130,1250 if vertical else 875),radius=28,fill=color('teal'))
        center(d,(w-40)/2,1136 if vertical else 817,'签证账单研究',56 if vertical else 39,'white')
        im.save(MEDIA/f'covers/{video_id}.png')
    # Small full-story contact sheet for review.
    cw,ch=324,576;sheet=Image.new('RGB',(cw*4,ch*2),color('paper'))
    for _,idx,im in [x for x in contact if x[0]=='flagship_vertical']:sheet.paste(im.resize((cw,ch)),((idx%4)*cw,(idx//4)*ch))
    sheet.save(MEDIA/'keyframes/flagship_contact_sheet.png')

def render(video_id):
    spec=VIDEOS[video_id];scenes,cues,audio_stats=audio_for(video_id,spec);save_srt(video_id,cues)
    duration=sum(s['duration'] for s in scenes);w,h=spec['size'];silent=MEDIA/f'exports/.{video_id}_silent.mp4';target=MEDIA/f'exports/{video_id}.mp4'
    cmd=[FFMPEG,'-v','error','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    si=0;nframes=round(duration*FPS)
    for fi in range(nframes):
        t=fi/FPS
        while si<len(scenes)-1 and t>=scenes[si]['end']:si+=1
        scene=scenes[si];im=frame(video_id,scene,t-scene['start'],t,duration,cues)
        proc.stdin.write(im.tobytes())
        if fi%(FPS*10)==0:print(json.dumps({'video':video_id,'seconds_rendered':round(t),'total':duration}),flush=True)
    proc.stdin.close();assert proc.wait()==0
    run([FFMPEG,'-v','error','-y','-i',silent,'-i',MEDIA/f'audio/{video_id}.wav','-c:v','copy','-c:a','aac','-b:a','192k','-ar','44100','-movflags','+faststart','-shortest',target]);silent.unlink()
    # Decode the final MP4 to the null muxer: detects corrupted video/audio, not merely container existence.
    run([FFMPEG,'-v','error','-i',target,'-f','null','-'])
    manifest=dict(video_id=video_id,title=spec['title'],size=[w,h],fps=FPS,frames=nframes,duration_seconds=duration,audio=audio_stats,
        subtitle_cues=len(cues),burned_subtitles=True,claim_ids=sorted(set(c for s in scenes for c in s['claim_ids'])),
        final_mp4=str(target.relative_to(ROOT)),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),decode_check='pass',
        audio_validation='Generated from listed sentences; per-sentence measured cue timing; decoded final AAC; waveform non-silence and no clipping. Subjective listening requires an audio-capable reviewer.')
    (MEDIA/f'evidence/{video_id}_validation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (MEDIA/f'evidence/{video_id}_timeline.json').write_text(json.dumps(scenes,ensure_ascii=False,indent=2))
    with (MEDIA/f'evidence/{video_id}_sentence_claims.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['start','end','text','scene','claim_ids','source_ids']);writer.writeheader()
        for c in cues:
            writer.writerow(dict(c,claim_ids=';'.join(c['claim_ids']),source_ids=';'.join(dict.fromkeys(s for cid in c['claim_ids'] for s in CLAIMS[cid]['source_ids']))))
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--keyframes',action='store_true');p.add_argument('--render',choices=['all']+list(VIDEOS));args=p.parse_args()
    if args.keyframes or not args.render:keyframes()
    if args.render:
        evidence()
        for video_id in VIDEOS if args.render=='all' else [args.render]:render(video_id)
if __name__=='__main__':main()
